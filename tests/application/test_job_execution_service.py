from __future__ import annotations

import threading
import time
from datetime import timedelta

from app.application.services.job_execution_service import (
    JobExecutionResult,
    JobExecutionService,
)

_IGNORE_SIGTERM_AND_SLEEP = (
    "import signal, time; "
    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "time.sleep(30)"
)


def test_execute_with_no_command_succeeds_immediately() -> None:
    service = JobExecutionService()

    result = service.execute(
        command=None,
        timeout=timedelta(seconds=1),
    )

    assert result.succeeded is True
    assert result.timed_out is False
    assert result.exit_code == 0


def test_execute_successful_command() -> None:
    service = JobExecutionService()

    result = service.execute(
        command=["python3", "-c", "print('hello')"],
        timeout=timedelta(seconds=5),
    )

    assert result.succeeded is True
    assert result.timed_out is False
    assert result.exit_code == 0
    assert "hello" in result.stdout


def test_execute_failing_command() -> None:
    service = JobExecutionService()

    result = service.execute(
        command=["python3", "-c", "import sys; sys.exit(1)"],
        timeout=timedelta(seconds=5),
    )

    assert result.succeeded is False
    assert result.timed_out is False
    assert result.exit_code == 1


def test_execute_terminates_gracefully_on_timeout() -> None:
    """
    A well-behaved process that respects SIGTERM should be
    stopped by the graceful signal alone, well within the
    grace period, never reaching SIGKILL.
    """
    service = JobExecutionService(
        termination_grace_period=timedelta(seconds=3),
    )

    result = service.execute(
        command=["python3", "-c", "import time; time.sleep(30)"],
        timeout=timedelta(seconds=0.5),
    )

    assert result.succeeded is False
    assert result.timed_out is True
    assert result.duration < timedelta(seconds=3)


def test_execute_force_kills_command_that_ignores_sigterm() -> None:
    """
    A process that explicitly ignores SIGTERM must still be
    stopped, via SIGKILL, once the grace period elapses.
    This is the test that actually proves the escalation
    path works, rather than only proving SIGTERM alone is
    often sufficient.
    """
    service = JobExecutionService(
        termination_grace_period=timedelta(seconds=1),
    )

    result = service.execute(
        command=["python3", "-c", _IGNORE_SIGTERM_AND_SLEEP],
        timeout=timedelta(seconds=0.5),
    )

    assert result.succeeded is False
    assert result.timed_out is True
    # Grace period (1s) + timeout budget (0.5s) + slack,
    # but nowhere near the process's own 30s sleep.
    assert result.duration < timedelta(seconds=5)


def test_execute_captures_stderr() -> None:
    service = JobExecutionService()

    result = service.execute(
        command=[
            "python3",
            "-c",
            "import sys; print('oops', file=sys.stderr)",
        ],
        timeout=timedelta(seconds=5),
    )

    assert "oops" in result.stderr


def test_execute_succeeds_normally_when_cancel_event_never_set() -> None:
    """
    Passing a cancel_event that's simply never triggered
    must not change normal, fast-completing behavior. The
    polling loop introduced for cancellation support should
    be invisible to a command that finishes on its own.
    """
    service = JobExecutionService()
    cancel_event = threading.Event()

    result = service.execute(
        command=["python3", "-c", "print('hello')"],
        timeout=timedelta(seconds=5),
        cancel_event=cancel_event,
    )

    assert result.succeeded is True
    assert result.cancelled is False


def test_execute_cancels_gracefully_when_event_is_set() -> None:
    """
    A well-behaved process should be stopped by SIGTERM
    alone once cancel_event fires, well within the grace
    period, distinct from a timeout (ADR 0029).
    """
    service = JobExecutionService(
        termination_grace_period=timedelta(seconds=3),
        poll_interval=timedelta(seconds=0.05),
    )
    cancel_event = threading.Event()

    def trigger_cancel() -> None:
        time.sleep(0.2)
        cancel_event.set()

    threading.Thread(target=trigger_cancel, daemon=True).start()

    result = service.execute(
        command=["python3", "-c", "import time; time.sleep(30)"],
        timeout=timedelta(seconds=10),
        cancel_event=cancel_event,
    )

    assert result.succeeded is False
    assert result.cancelled is True
    assert result.timed_out is False
    assert result.duration < timedelta(seconds=3)


def test_execute_force_kills_command_that_ignores_sigterm_on_cancel() -> None:
    """
    The same escalation to SIGKILL already proven for the
    timeout path must also work when cancellation is the
    trigger, since _terminate_early is shared between both.
    """
    service = JobExecutionService(
        termination_grace_period=timedelta(seconds=1),
        poll_interval=timedelta(seconds=0.05),
    )
    cancel_event = threading.Event()

    def trigger_cancel() -> None:
        time.sleep(0.2)
        cancel_event.set()

    threading.Thread(target=trigger_cancel, daemon=True).start()

    result = service.execute(
        command=["python3", "-c", _IGNORE_SIGTERM_AND_SLEEP],
        timeout=timedelta(seconds=10),
        cancel_event=cancel_event,
    )

    assert result.succeeded is False
    assert result.cancelled is True
    # Grace period (1s) + cancel delay (0.2s) + slack,
    # but nowhere near the process's own 30s sleep.
    assert result.duration < timedelta(seconds=5)


def test_succeeded_is_false_when_cancelled_even_with_zero_exit_code() -> None:
    """
    A process terminated by SIGTERM can still report a zero
    or coincidental exit code. cancelled must independently
    force succeeded to False regardless of exit_code.
    """
    result = JobExecutionResult(
        exit_code=0,
        timed_out=False,
        cancelled=True,
        duration=timedelta(seconds=0),
        stdout="",
        stderr="",
    )

    assert result.succeeded is False
