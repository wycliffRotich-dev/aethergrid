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

    timed_out and cancelled are deliberately separate flags,
    not one combined "we killed it" boolean. Both end in the
    same SIGTERM-then-SIGKILL escalation, but they mean
    different things to a caller: timed_out means the job
    itself ran too long, cancelled means someone asked for it
    to stop (ADR 0029). Collapsing them would make a
    cancelled job indistinguishable from one that simply
    misbehaved, in logs, events, or future alerting.
    """

    exit_code: int | None
    timed_out: bool
    cancelled: bool
    duration: timedelta
    stdout: str
    stderr: str

    @property
    def succeeded(self) -> bool:
        return (
            not self.timed_out
            and not self.cancelled
            and self.exit_code == 0
        )


class JobExecutionService:
    """
    Executes a job's command as a real subprocess, with
    real timeout enforcement and real cancellation support
    (ADR 0029).

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
    ) -> JobExecutionResult:
        """
        Run command to completion, or until it times out or
        cancel_event is set, whichever happens first.

        Waiting happens in short polling intervals rather
        than one long blocking call specifically so
        cancel_event can be checked while the process is
        still running. Python's subprocess.communicate()
        supports being called repeatedly after a
        TimeoutExpired without harming the child process --
        it is still running and waiting for us when we come
        back -- so this polling loop costs nothing beyond the
        wakeups themselves.
        """
        if command is None:
            return JobExecutionResult(
                exit_code=0,
                timed_out=False,
                cancelled=False,
                duration=timedelta(seconds=0),
                stdout="",
                stderr="",
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
    ) -> JobExecutionResult:
        """
        Escalate from a graceful SIGTERM to a forceful
        SIGKILL if the process doesn't exit within the
        grace period. This mirrors how real orchestrators
        (systemd, Kubernetes, Docker) handle shutdown: give
        the process a chance to clean up, then guarantee it
        actually stops.

        Used identically whether the job overran its timeout
        or was asked to cancel (ADR 0029) -- the shutdown
        sequence doesn't change, only which of timed_out or
        cancelled the caller sets to record why.

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
        )
