from __future__ import annotations

import contextlib
import errno
import logging
import os
import signal
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

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


# A command that starts a child with its output detached, records the
# child's pid and exits at once. The child is detached so that the
# command's own output pipes close when the command exits.
_EXIT_LEAVING_A_CHILD = (
    "import subprocess, sys; "
    "child = subprocess.Popen(['sleep', '60'], "
    "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
    "stderr=subprocess.DEVNULL); "
    "open(sys.argv[1], 'w').write(str(child.pid))"
)

# A child that ignores SIGTERM and records its own pid only after it
# does, so a test never signals it before the handler is in place.
_CHILD_THAT_IGNORES_SIGTERM = (
    "import os, signal, sys, time; "
    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "open(sys.argv[1], 'w').write(str(os.getpid())); "
    "time.sleep(60)"
)

# A command that starts that child with its output detached and then
# waits. The command dies on SIGTERM and the child does not.
_SPAWN_A_DETACHED_CHILD_THAT_IGNORES_SIGTERM = (
    "import subprocess, sys, time; "
    "subprocess.Popen(['python3', '-c', sys.argv[2], sys.argv[1]], "
    "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
    "stderr=subprocess.DEVNULL); "
    "time.sleep(60)"
)


def test_a_command_that_exits_leaves_no_children_behind(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "child.pid"
    service = JobExecutionService(
        termination_grace_period=timedelta(seconds=1),
    )
    child_pid = None

    try:
        result = service.execute(
            command=["python3", "-c", _EXIT_LEAVING_A_CHILD, str(pid_file)],
            timeout=timedelta(seconds=30),
        )
        child_pid = _wait_for_pid(pid_file, seconds=1.0)

        assert result.succeeded is True
        assert child_pid is not None
        assert _wait_until_gone(child_pid)
    finally:
        _kill_leftover(child_pid)


def test_a_descendant_that_ignores_sigterm_is_killed_when_the_command_exits(
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
                _SPAWN_A_DETACHED_CHILD_THAT_IGNORES_SIGTERM,
                str(pid_file),
                _CHILD_THAT_IGNORES_SIGTERM,
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


def test_a_signal_the_kernel_refuses_does_not_discard_the_result(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def refuse(pgid: int, sig: int) -> None:
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "killpg", refuse)
    service = JobExecutionService()

    with caplog.at_level(
        logging.WARNING,
        logger="app.application.services.job_execution_service",
    ):
        result = service.execute(
            command=["python3", "-c", "print('done')"],
            timeout=timedelta(seconds=5),
        )

    assert result.succeeded is True
    assert "done" in result.stdout
    assert "process group" in caplog.text
