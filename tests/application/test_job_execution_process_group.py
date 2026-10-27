from __future__ import annotations

import contextlib
import os
import signal
import threading
import time
from datetime import timedelta
from pathlib import Path

from app.application.services.job_execution_service import (
    JobExecutionService,
)

# A command that starts a child of its own, records the child's pid in
# the file named by its first argument, and then waits.
_SPAWN_A_CHILD = (
    "import subprocess, sys, time; "
    "child = subprocess.Popen(['sleep', '60']); "
    "open(sys.argv[1], 'w').write(str(child.pid)); "
    "time.sleep(60)"
)

# The same, but the child ignores SIGTERM, so only SIGKILL stops it.
_SPAWN_A_CHILD_THAT_IGNORES_SIGTERM = (
    "import subprocess, sys, time; "
    "child = subprocess.Popen(['python3', '-c', "
    "'import signal, time; "
    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "time.sleep(60)']); "
    "open(sys.argv[1], 'w').write(str(child.pid)); "
    "time.sleep(60)"
)


def _wait_for_pid(path: Path, seconds: float = 10.0) -> int | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return int(path.read_text())
        time.sleep(0.02)
    return None


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            state = handle.read().rsplit(")", 1)[1].split()[0]
    except OSError:
        # With /proc present, a missing entry means the process is
        # gone. Without /proc, the signal check above is all we have.
        return not Path("/proc/self").exists()
    # A zombie has exited and is only waiting to be reaped.
    return state != "Z"


def _wait_until_gone(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _is_running(pid):
            return True
        time.sleep(0.05)
    return not _is_running(pid)


def _kill_leftover(pid: int | None) -> None:
    if pid is None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)


def _set_when_a_child_exists(path: Path, event: threading.Event) -> None:
    if _wait_for_pid(path) is not None:
        event.set()


def test_a_lost_lease_stops_the_children_of_the_command(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "child.pid"
    lease_lost = threading.Event()
    threading.Thread(
        target=_set_when_a_child_exists,
        args=(pid_file, lease_lost),
        daemon=True,
    ).start()
    service = JobExecutionService(
        termination_grace_period=timedelta(seconds=1),
    )
    child_pid = None

    try:
        result = service.execute(
            command=["python3", "-c", _SPAWN_A_CHILD, str(pid_file)],
            timeout=timedelta(seconds=30),
            lease_lost_event=lease_lost,
        )
        child_pid = _wait_for_pid(pid_file, seconds=1.0)

        assert result.lease_lost is True
        assert child_pid is not None
        assert _wait_until_gone(child_pid)
    finally:
        _kill_leftover(child_pid)


def test_a_timeout_stops_the_children_of_the_command(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "child.pid"
    service = JobExecutionService(
        termination_grace_period=timedelta(seconds=1),
    )
    child_pid = None

    try:
        result = service.execute(
            command=["python3", "-c", _SPAWN_A_CHILD, str(pid_file)],
            timeout=timedelta(seconds=4),
        )
        child_pid = _wait_for_pid(pid_file, seconds=1.0)

        assert result.timed_out is True
        assert child_pid is not None
        assert _wait_until_gone(child_pid)
    finally:
        _kill_leftover(child_pid)


def test_a_child_that_ignores_sigterm_is_killed_after_the_grace_period(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "child.pid"
    lease_lost = threading.Event()
    threading.Thread(
        target=_set_when_a_child_exists,
        args=(pid_file, lease_lost),
        daemon=True,
    ).start()
    service = JobExecutionService(
        termination_grace_period=timedelta(seconds=1),
    )
    child_pid = None

    try:
        result = service.execute(
            command=[
                "python3",
                "-c",
                _SPAWN_A_CHILD_THAT_IGNORES_SIGTERM,
                str(pid_file),
            ],
            timeout=timedelta(seconds=30),
            lease_lost_event=lease_lost,
        )
        child_pid = _wait_for_pid(pid_file, seconds=1.0)

        assert result.lease_lost is True
        assert child_pid is not None
        assert _wait_until_gone(child_pid)
    finally:
        _kill_leftover(child_pid)


class _InterruptsOnceAChildExists(threading.Event):
    """
    A cancel event whose check is interrupted, as a Ctrl-C interrupts
    the wait, as soon as the command has started a child.
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    def is_set(self) -> bool:
        if self._path.exists() and self._path.stat().st_size > 0:
            raise KeyboardInterrupt
        return super().is_set()


def test_an_interrupt_while_waiting_stops_the_children_of_the_command(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "child.pid"
    service = JobExecutionService(
        termination_grace_period=timedelta(seconds=1),
    )
    child_pid = None
    interrupted = False

    try:
        try:
            service.execute(
                command=["python3", "-c", _SPAWN_A_CHILD, str(pid_file)],
                timeout=timedelta(seconds=30),
                cancel_event=_InterruptsOnceAChildExists(pid_file),
            )
        except KeyboardInterrupt:
            interrupted = True
        child_pid = _wait_for_pid(pid_file, seconds=1.0)

        assert interrupted is True
        assert child_pid is not None
        assert _wait_until_gone(child_pid)
    finally:
        _kill_leftover(child_pid)
