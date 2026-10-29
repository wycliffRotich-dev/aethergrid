from __future__ import annotations

import signal
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from app.application.services.job_execution_service import (
    JobExecutionService,
)

# What a caller sees from execute(), pinned before the command starts
# going through a supervisor (ADR 0080). These pass on the code as it
# is, and they must keep passing when the supervisor is in front of it.


def _python(script: str, *args: str) -> list[str]:
    return ["python3", "-c", script, *args]


def _service() -> JobExecutionService:
    return JobExecutionService(
        termination_grace_period=timedelta(seconds=1),
    )


def _set_when_the_file_exists(path: Path, event: threading.Event) -> None:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if path.exists():
            event.set()
            return
        time.sleep(0.02)


def _cancel_when_ready(ready_file: Path) -> threading.Event:
    cancel = threading.Event()
    threading.Thread(
        target=_set_when_the_file_exists,
        args=(ready_file, cancel),
        daemon=True,
    ).start()
    return cancel


def test_a_nonzero_exit_code_is_reported_as_it_is() -> None:
    result = _service().execute(
        command=_python("import sys; sys.exit(7)"),
        timeout=timedelta(seconds=15),
    )

    assert result.exit_code == 7
    assert result.succeeded is False
    assert result.timed_out is False
    assert result.cancelled is False
    assert result.lease_lost is False


def test_a_command_killed_by_a_signal_reports_the_negated_signal() -> None:
    result = _service().execute(
        command=_python(
            "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"
        ),
        timeout=timedelta(seconds=15),
    )

    assert result.exit_code == -int(signal.SIGKILL)
    assert result.succeeded is False
    assert result.timed_out is False


def test_a_timeout_reports_the_signal_that_ended_the_command() -> None:
    result = _service().execute(
        command=_python("import time; time.sleep(60)"),
        timeout=timedelta(seconds=0.5),
    )

    assert result.timed_out is True
    assert result.exit_code == -int(signal.SIGTERM)
    assert result.succeeded is False


@pytest.mark.parametrize("reason", ["cancelled", "lease_lost"])
def test_a_stop_reports_the_signal_that_ended_the_command(
    reason: str,
) -> None:
    event = threading.Event()
    event.set()
    events = (
        {"cancel_event": event}
        if reason == "cancelled"
        else {"lease_lost_event": event}
    )

    result = _service().execute(
        command=_python("import time; time.sleep(60)"),
        timeout=timedelta(seconds=15),
        **events,
    )

    assert result.exit_code == -int(signal.SIGTERM)
    assert result.cancelled is (reason == "cancelled")
    assert result.lease_lost is (reason == "lease_lost")
    assert result.timed_out is False
    assert result.succeeded is False


def test_a_command_that_handles_sigterm_keeps_its_own_exit_code(
    tmp_path: Path,
) -> None:
    ready = tmp_path / "ready"
    script = (
        "import signal, sys, time; "
        "signal.signal(signal.SIGTERM, lambda *a: sys.exit(3)); "
        "open(sys.argv[1], 'w').write('ready'); "
        "time.sleep(60)"
    )

    result = _service().execute(
        command=_python(script, str(ready)),
        timeout=timedelta(seconds=15),
        cancel_event=_cancel_when_ready(ready),
    )

    assert result.cancelled is True
    assert result.exit_code == 3
    assert result.succeeded is False


def test_a_command_that_ignores_sigterm_is_killed_and_reports_sigkill(
    tmp_path: Path,
) -> None:
    ready = tmp_path / "ready"
    script = (
        "import signal, sys, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "open(sys.argv[1], 'w').write('ready'); "
        "time.sleep(60)"
    )

    result = _service().execute(
        command=_python(script, str(ready)),
        timeout=timedelta(seconds=15),
        cancel_event=_cancel_when_ready(ready),
    )

    assert result.cancelled is True
    assert result.exit_code == -int(signal.SIGKILL)
    assert result.succeeded is False


def test_output_is_returned_as_written() -> None:
    result = _service().execute(
        command=_python(
            "import sys; sys.stdout.write('out\\n'); sys.stderr.write('err\\n')"
        ),
        timeout=timedelta(seconds=15),
    )

    assert result.succeeded is True
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"


def test_output_written_before_a_stop_is_kept(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    script = (
        "import sys, time; "
        "sys.stdout.write('started\\n'); sys.stdout.flush(); "
        "sys.stderr.write('warned\\n'); sys.stderr.flush(); "
        "open(sys.argv[1], 'w').write('ready'); "
        "time.sleep(60)"
    )

    result = _service().execute(
        command=_python(script, str(ready)),
        timeout=timedelta(seconds=15),
        cancel_event=_cancel_when_ready(ready),
    )

    assert result.cancelled is True
    assert result.stdout == "started\n"
    assert result.stderr == "warned\n"
