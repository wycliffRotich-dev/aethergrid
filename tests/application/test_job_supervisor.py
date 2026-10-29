from __future__ import annotations

import contextlib
import errno
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import TracebackType

import pytest

from app.application.services.job_supervisor import (
    LAUNCH_FAILED_EXIT_CODE,
    USAGE_EXIT_CODE,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = "app.application.services.job_supervisor"

# A command that starts a child of its own, records the child's pid in
# the file named by its first argument, and then waits.
_SPAWN_A_CHILD = (
    "import subprocess, sys, time; "
    "child = subprocess.Popen(['sleep', '60']); "
    "open(sys.argv[1], 'w').write(str(child.pid)); "
    "time.sleep(60)"
)


def _wait_for(path: Path, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return True
        time.sleep(0.02)
    return False


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            state = handle.read().rsplit(")", 1)[1].split()[0]
    except OSError:
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


class _Supervised:
    """
    The supervisor as the owner starts it: a new session, the read end
    of the watch pipe, the write end of the status pipe. Whatever is
    left of the group is killed on the way out, even if a test fails.
    """

    def __init__(self, command: list[str], *, own_session: bool = True) -> None:
        self._own_session = own_session
        watch_read, watch_write = os.pipe()
        status_read, status_write = os.pipe()
        self._watch_write: int | None = watch_write
        self._status_read = status_read
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                MODULE,
                str(watch_read),
                str(status_write),
                "--",
                *command,
            ],
            pass_fds=(watch_read, status_write),
            start_new_session=own_session,
            cwd=REPO_ROOT,
        )
        os.close(watch_read)
        os.close(status_write)

    def close_owner_end(self) -> None:
        if self._watch_write is not None:
            os.close(self._watch_write)
            self._watch_write = None

    def status(self) -> bytes:
        return os.read(self._status_read, 4096)

    def __enter__(self) -> _Supervised:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        with contextlib.suppress(ProcessLookupError):
            if self._own_session:
                os.killpg(self.process.pid, signal.SIGKILL)
            else:
                self.process.kill()
        self.process.wait()
        self.close_owner_end()
        os.close(self._status_read)


def test_it_exits_with_the_exit_code_of_the_command() -> None:
    with _Supervised(["python3", "-c", "import sys; sys.exit(7)"]) as sup:
        assert sup.process.wait(timeout=10) == 7
        assert sup.status() == b""


@pytest.mark.parametrize(
    "number", [signal.SIGTERM, signal.SIGKILL, signal.SIGUSR1]
)
def test_it_dies_of_the_signal_that_killed_the_command(
    number: signal.Signals,
) -> None:
    script = f"import os; os.kill(os.getpid(), {int(number)})"

    with _Supervised(["python3", "-c", script]) as sup:
        assert sup.process.wait(timeout=10) == -int(number)


def test_a_sigterm_to_the_group_leaves_the_command_to_decide(
    tmp_path: Path,
) -> None:
    ready = tmp_path / "ready"
    script = (
        "import signal, sys, time; "
        "signal.signal(signal.SIGTERM, lambda *a: sys.exit(3)); "
        "open(sys.argv[1], 'w').write('ready'); "
        "time.sleep(60)"
    )

    with _Supervised(["python3", "-c", script, str(ready)]) as sup:
        assert _wait_for(ready)
        os.killpg(sup.process.pid, signal.SIGTERM)

        assert sup.process.wait(timeout=10) == 3


def test_the_group_is_killed_when_the_owner_end_of_the_pipe_closes(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "child.pid"

    with _Supervised(
        ["python3", "-c", _SPAWN_A_CHILD, str(pid_file)]
    ) as sup:
        assert _wait_for(pid_file)
        child_pid = int(pid_file.read_text())

        sup.close_owner_end()

        assert sup.process.wait(timeout=10) == -int(signal.SIGKILL)
        assert _wait_until_gone(child_pid)


def test_a_command_that_cannot_start_is_reported_on_the_status_pipe(
    tmp_path: Path,
) -> None:
    missing = str(tmp_path / "no-such-binary")

    with _Supervised([missing]) as sup:
        assert sup.process.wait(timeout=10) == LAUNCH_FAILED_EXIT_CODE
        report = json.loads(sup.status())

    assert report["errno"] == errno.ENOENT
    assert report["filename"] == missing


def test_it_refuses_to_run_unless_it_leads_its_own_group(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "ran"
    script = "import sys; open(sys.argv[1], 'w').write('ran')"

    with _Supervised(
        ["python3", "-c", script, str(marker)], own_session=False
    ) as sup:
        assert sup.process.wait(timeout=10) == USAGE_EXIT_CODE

    assert not marker.exists()
