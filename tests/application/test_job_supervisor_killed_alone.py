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

# A command that records its own pid and its parent's pid in the file
# named by its first argument, and then waits. Its parent is the
# supervisor.
_RECORD_PIDS = (
    "import os, sys, time; "
    "open(sys.argv[1], 'w').write(f'{os.getpid()} {os.getppid()}'); "
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


def test_a_supervisor_killed_alone_leaves_the_command_until_the_job_ends(
    tmp_path: Path,
) -> None:
    """
    ADR 0080. Only the supervisor is killed, so no end of file reaches
    the watch and nothing ends the group at once. The command keeps
    running while the owner waits for the pipes it holds, and the job
    ends at its timeout, when the owner signals the group. This pins
    that behavior and its cost: the command runs for as long as the
    timeout allows.
    """
    pid_file = tmp_path / "pids"
    seen: dict[str, int] = {}
    survived: list[bool] = []

    def kill_the_supervisor() -> None:
        if not _wait_for(pid_file):
            return
        command_pid, supervisor_pid = (
            int(value) for value in pid_file.read_text().split()
        )
        seen["command_pid"] = command_pid
        os.kill(supervisor_pid, signal.SIGKILL)
        time.sleep(0.5)
        survived.append(_is_running(command_pid))

    threading.Thread(target=kill_the_supervisor, daemon=True).start()

    try:
        result = JobExecutionService(
            termination_grace_period=timedelta(seconds=1),
        ).execute(
            command=["python3", "-c", _RECORD_PIDS, str(pid_file)],
            timeout=timedelta(seconds=4),
        )

        assert "command_pid" in seen, "the command never recorded its pids"
        assert survived == [True], "the command ended with the supervisor"
        assert result.timed_out is True
        assert result.exit_code == -int(signal.SIGKILL)
        assert _wait_until_gone(seen["command_pid"])
    finally:
        if "command_pid" in seen:
            with contextlib.suppress(ProcessLookupError):
                os.kill(seen["command_pid"], signal.SIGKILL)
