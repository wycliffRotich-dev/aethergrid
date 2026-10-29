from __future__ import annotations

import contextlib
import json
import logging
import os
import select
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta

logger = logging.getLogger(__name__)

DEFAULT_TERMINATION_GRACE_PERIOD = timedelta(seconds=5)
DEFAULT_POLL_INTERVAL = timedelta(seconds=0.2)

# Faults of the command itself that stop it from starting (ADR 0081).
# A fault of the host, such as a failed fork, is not in this list and
# still raises.
_LAUNCH_FAULTS = (
    FileNotFoundError,
    PermissionError,
    NotADirectoryError,
)

_SUPERVISOR_MODULE = "app.application.services.job_supervisor"


class _Pending:
    """The supervisor has not said yet whether the command started."""


_PENDING = _Pending()


def _signal_group(process: subprocess.Popen[str], sig: int) -> None:
    """
    Send sig to the whole process group of process.

    The command runs in its own session, so its group id is its pid
    and the group holds the command and everything it started. A group
    that is already gone is not an error. A signal the kernel refuses
    is logged and not raised, because this runs after a job has ended
    and must not discard its result (ADR 0079).
    """
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        return
    except PermissionError:
        logger.warning(
            "Not permitted to send %s to process group %s, so a "
            "process of the job may be left running.",
            signal.Signals(sig).name,
            process.pid,
        )


@contextlib.contextmanager
def _kill_the_group_on_exit(
    process: subprocess.Popen[str],
) -> Iterator[None]:
    """
    Kill the whole process group when the wait ends, for any reason.

    Whatever the command left running is killed before execute()
    returns, whether the command exited, was stopped, or an exception
    escaped the wait, a KeyboardInterrupt included. A group with no
    member left is not an error (ADR 0079).

    The command is in its own session, so a Ctrl-C that reaches the
    agent no longer reaches it. Without this, the agent would stop
    waiting while the work went on after its lease expired.
    """
    try:
        yield
    finally:
        _signal_group(process, signal.SIGKILL)


def _start_supervised(
    command: list[str],
) -> tuple[subprocess.Popen[str], int, int]:
    """
    Start the supervisor, and through it the command (ADR 0080).

    Returns the supervisor's process and the two pipe ends this process
    keeps: the write end of the watch pipe and the read end of the
    status pipe. The ends the supervisor uses are closed here once it
    has them. The ends kept here are not inheritable, so no other job
    started by this process holds the write end, which would keep the
    supervisor from ever reading end of file.

    -P keeps the working directory off sys.path, so a job started in a
    directory with an app package of its own cannot make the supervisor
    import that one.
    """
    watch_read, watch_write = os.pipe()
    status_read, status_write = os.pipe()

    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-P",
                "-m",
                _SUPERVISOR_MODULE,
                str(watch_read),
                str(status_write),
                "--",
                *command,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            pass_fds=(watch_read, status_write),
        )
    except BaseException:
        os.close(watch_write)
        os.close(status_read)
        raise
    finally:
        os.close(watch_read)
        os.close(status_write)

    return process, watch_write, status_read


@contextlib.contextmanager
def _close_on_exit(*descriptors: int) -> Iterator[None]:
    try:
        yield
    finally:
        for descriptor in descriptors:
            with contextlib.suppress(OSError):
                os.close(descriptor)


def _read_launch_failure(
    status_read: int, deadline: float
) -> OSError | _Pending | None:
    """
    Wait for the supervisor to say whether the command started.

    The supervisor closes the status pipe once the command is running.
    If it could not start the command, it writes why and then closes
    it. Nothing by the deadline is _PENDING, and the wait loop asks
    again after it has checked the stop events and the timeout, so a
    supervisor that stays silent is stopped like any other job.
    """
    remaining = max(0.0, deadline - time.monotonic())
    ready, _, _ = select.select([status_read], [], [], remaining)

    if not ready:
        return _PENDING

    data = b""
    while chunk := os.read(status_read, 4096):
        data += chunk

    if not data:
        return None

    try:
        report = json.loads(data)
        return OSError(report["errno"], report["strerror"], report["filename"])
    except (ValueError, KeyError, TypeError):
        # A supervisor killed in the middle of its report leaves a part of
        # it. That is not a launch failure to act on, so the wait loop
        # reports how the supervisor ended.
        logger.warning(
            "unreadable launch report from the job supervisor: %r", data[:200]
        )
        return None


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

        # A fault of the host while starting the supervisor, such as a
        # missing interpreter, is not a fault of the job, so it raises
        # (ADR 0081, Decision 3). A command that cannot start is
        # reported by the supervisor and handled in the loop below.
        process, watch_write, status_read = _start_supervised(command)
        launch_pending = True

        with (
            process,
            _close_on_exit(watch_write, status_read),
            _kill_the_group_on_exit(process),
        ):
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

                if launch_pending:
                    # Waiting for the supervisor to report is bounded by
                    # one poll interval, so a cancel, a lost lease or a
                    # timeout is acted on while it is still silent.
                    failure = _read_launch_failure(
                        status_read,
                        time.monotonic() + wait_for,
                    )

                    if isinstance(failure, _Pending):
                        continue

                    launch_pending = False

                    if failure is not None:
                        if not isinstance(failure, _LAUNCH_FAULTS):
                            raise failure

                        return self._could_not_start(command, failure, start)

                    continue

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
                    if process.poll() is None:
                        continue

                    # The supervisor has ended, so the pipes are not what
                    # tells us the job is over: a child of the command may
                    # still hold them. End the group and collect what is
                    # left (ADR 0083).
                    return self._collect_after_supervisor_ended(process, start)

    def _collect_after_supervisor_ended(
        self,
        process: subprocess.Popen[str],
        start: float,
    ) -> JobExecutionResult:
        """
        The result of a job whose supervisor ended while the pipes were
        still open (ADR 0083).

        The supervisor ends with the command, or alone if it was killed.
        Either way something in the group can still hold stdout and
        stderr, and communicate() would wait for it until the timeout.
        The group is killed, the output is collected, and the result is
        the supervisor's own: the command's exit code, or the signal that
        ended the supervisor. It is not a timeout, because the job did
        not overrun.
        """
        _signal_group(process, signal.SIGKILL)

        try:
            stdout, stderr = process.communicate(
                timeout=self._termination_grace_period.total_seconds(),
            )
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""

        return JobExecutionResult(
            exit_code=process.returncode,
            timed_out=False,
            cancelled=False,
            duration=timedelta(seconds=time.monotonic() - start),
            stdout=stdout,
            stderr=stderr,
            lease_lost=False,
        )

    def _could_not_start(
        self,
        command: list[str],
        error: OSError,
        start: float,
    ) -> JobExecutionResult:
        """
        The result of a command that could not be started (ADR 0081).

        A missing, unreadable or non-executable file is a fault of
        the job's command, so the job fails like any other failed job
        and the caller reports it under its lease. The reason goes in
        stderr and in the log. Only the program name is logged, never
        its arguments, which can hold secrets.
        """
        logger.warning(
            "The command %r could not be started: %s",
            command[0],
            error.strerror,
        )

        return JobExecutionResult(
            exit_code=None,
            timed_out=False,
            cancelled=False,
            duration=timedelta(seconds=time.monotonic() - start),
            stdout="",
            stderr=f"The command could not be started: {error}\n",
            lease_lost=False,
        )

    def _terminate_early(
        self,
        process: subprocess.Popen[str],
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
        # The command runs in its own session, so this reaches
        # everything it started and not only the command itself.
        _signal_group(process, signal.SIGTERM)

        try:
            stdout, stderr = process.communicate(
                timeout=self._termination_grace_period.total_seconds(),
            )
        except subprocess.TimeoutExpired:
            _signal_group(process, signal.SIGKILL)

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
