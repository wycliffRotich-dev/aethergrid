from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import timedelta

DEFAULT_TERMINATION_GRACE_PERIOD = timedelta(seconds=5)
DEFAULT_POLL_INTERVAL = timedelta(seconds=0.2)


@dataclass(frozen=True, slots=True)
class JobExecutionResult:
    """
    The outcome of one real subprocess execution attempt.

    timed_out, cancelled, and lease_lost are deliberately
    separate flags, not one combined "we killed it" boolean.
    All three end in the same SIGTERM-then-SIGKILL
    escalation, but they mean different things to a caller:
    timed_out means the job itself ran too long, cancelled
    means someone asked for it to stop (ADR 0029), and
    lease_lost means the fleet reassigned this job to another
    worker while it was still running (ADR 0044's known gap).
    Collapsing them would make a reclaimed job indistinguishable
    from an operator-initiated cancel -- and callers rely on
    that distinction to decide whether to report an outcome at
    all, since a lease-lost job has nothing left to report.
    """

    exit_code: int | None
    timed_out: bool
    cancelled: bool
    duration: timedelta
    stdout: str
    stderr: str
    lease_lost: bool = False

    @property
    def succeeded(self) -> bool:
        return (
            not self.timed_out
            and not self.cancelled
            and not self.lease_lost
            and self.exit_code == 0
        )


class JobExecutionService:
    """
    Executes a job's command as a real subprocess, with
    real timeout enforcement, real cancellation support
    (ADR 0029), and real lease-loss preemption (ADR 0044
    follow-up).

    A job with no command set (the current default for
    every job created through the public API -- see
    Job.command's docstring and ADR 0012) is treated as a
    no-op success: this lets the rest of the execution
    pipeline (timeout enforcement, result branching,
    worker state transitions) be exercised end-to-end
    without requiring every job to carry a real command
    yet.
    """

    def __init__(
        self,
        termination_grace_period: timedelta = DEFAULT_TERMINATION_GRACE_PERIOD,
        poll_interval: timedelta = DEFAULT_POLL_INTERVAL,
    ) -> None:
        self._termination_grace_period = termination_grace_period
        self._poll_interval = poll_interval

    def execute(
        self,
        command: list[str] | None,
        timeout: timedelta,
        cancel_event: threading.Event | None = None,
        lease_lost_event: threading.Event | None = None,
    ) -> JobExecutionResult:
        """
        Run command to completion, or until it times out,
        cancel_event is set, or lease_lost_event is set --
        whichever happens first.

        lease_lost_event is checked on the same polling
        cadence as cancel_event, for the same reason: a
        subprocess is a blocking OS resource, and the only
        way to preempt it before natural exit is to interrupt
        a wait that's already broken into short slices.
        Without this, a lease reclaimed mid-run would have no
        effect until the subprocess exited on its own (ADR
        0044's documented gap) -- the caller's post-hoc check
        of the same event is then too late to stop the work,
        only too late to report it.

        Waiting happens in short polling intervals rather
        than one long blocking call specifically so
        cancel_event and lease_lost_event can be checked
        while the process is still running. Python's
        subprocess.communicate() supports being called
        repeatedly after a TimeoutExpired without harming the
        child process -- it is still running and waiting for
        us when we come back -- so this polling loop costs
        nothing beyond the wakeups themselves.
        """
        if command is None:
            return JobExecutionResult(
                exit_code=0,
                timed_out=False,
                cancelled=False,
                duration=timedelta(seconds=0),
                stdout="",
                stderr="",
                lease_lost=False,
            )

        start = time.monotonic()
        deadline = start + timeout.total_seconds()
        poll_interval_seconds = self._poll_interval.total_seconds()

        with subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as process:
            while True:
                remaining = deadline - time.monotonic()

                if remaining <= 0:
                    return self._terminate_early(
                        process,
                        start,
                        timed_out=True,
                        cancelled=False,
                        lease_lost=False,
                    )

                if (
                    lease_lost_event is not None
                    and lease_lost_event.is_set()
                ):
                    return self._terminate_early(
                        process,
                        start,
                        timed_out=False,
                        cancelled=False,
                        lease_lost=True,
                    )

                if (
                    cancel_event is not None
                    and cancel_event.is_set()
                ):
                    return self._terminate_early(
                        process,
                        start,
                        timed_out=False,
                        cancelled=True,
                        lease_lost=False,
                    )

                wait_for = min(
                    poll_interval_seconds,
                    remaining,
                )

                try:
                    stdout, stderr = process.communicate(
                        timeout=wait_for,
                    )

                    duration = timedelta(
                        seconds=time.monotonic() - start,
                    )

                    return JobExecutionResult(
                        exit_code=process.returncode,
                        timed_out=False,
                        cancelled=False,
                        duration=duration,
                        stdout=stdout,
                        stderr=stderr,
                        lease_lost=False,
                    )

                except subprocess.TimeoutExpired:
                    continue

    def _terminate_early(
        self,
        process: subprocess.Popen,
        start: float,
        *,
        timed_out: bool,
        cancelled: bool,
        lease_lost: bool = False,
    ) -> JobExecutionResult:
        """
        Escalate from a graceful SIGTERM to a forceful
        SIGKILL if the process doesn't exit within the
        grace period. This mirrors how real orchestrators
        (systemd, Kubernetes, Docker) handle shutdown: give
        the process a chance to clean up, then guarantee it
        actually stops.

        Used identically whether the job overran its timeout,
        was asked to cancel (ADR 0029), or lost its lease to
        another worker (ADR 0044 follow-up) -- the shutdown
        sequence doesn't change, only which of timed_out,
        cancelled, or lease_lost the caller sets to record why.

        The final communicate() after kill() still carries a
        timeout. SIGKILL cannot be blocked or ignored by a
        well-behaved process on Linux, but a hung or
        zombie/defunct process is a real (if rare) failure
        mode worth bounding rather than trusting
        unconditionally.
        """
        process.terminate()

        try:
            stdout, stderr = process.communicate(
                timeout=self._termination_grace_period.total_seconds(),
            )
        except subprocess.TimeoutExpired:
            process.kill()

            try:
                stdout, stderr = process.communicate(
                    timeout=self._termination_grace_period.total_seconds(),
                )
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""

        duration = timedelta(
            seconds=time.monotonic() - start,
        )

        return JobExecutionResult(
            exit_code=process.returncode,
            timed_out=timed_out,
            cancelled=cancelled,
            duration=duration,
            stdout=stdout,
            stderr=stderr,
            lease_lost=lease_lost,
        )
