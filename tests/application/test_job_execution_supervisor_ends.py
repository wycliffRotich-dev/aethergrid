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

# Records its own pid and its parent's pid, which is the supervisor's, in
# the file named by its first argument, and then waits.
_RECORD_PIDS = (
    "import os, sys, time; "
    "open(sys.argv[1], 'w').write(f'{os.getpid()} {os.getppid()}'); "
    "time.sleep(60)"
)

# Starts a child that inherits stdout and stderr, records the child's pid
# and exits at once with code 0.
_LEAVE_A_CHILD = (
    "import subprocess, sys; "
    "child = subprocess.Popen(['sleep', '60']); "
    "open(sys.argv[1], 'w').write(str(child.pid))"
)

# The job has a long timeout, so a job that ends at its timeout takes
# twice as long as this and fails the check.
TIMEOUT = timedelta(seconds=10)
PROMPT_SECONDS = 5.0


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


def test_a_job_ends_when_its_supervisor_is_killed_alone(
    tmp_path: Path,
) -> None:
    """
    ADR 0080. Only the supervisor is killed, so no end of file reaches
    its watch. The command still holds the pipes, so the owner never
    reads end of file from them. The owner has to see that the
    supervisor is gone and end the group, and not wait for the timeout.
    """
    pid_file = tmp_path / "pids"
    seen: dict[str, int] = {}

    def kill_the_supervisor() -> None:
        if not _wait_for(pid_file):
            return
        command_pid, supervisor_pid = (
            int(value) for value in pid_file.read_text().split()
        )
        seen["command_pid"] = command_pid
        os.kill(supervisor_pid, signal.SIGKILL)

    threading.Thread(target=kill_the_supervisor, daemon=True).start()

    try:
        started = time.monotonic()
        result = JobExecutionService(
            termination_grace_period=timedelta(seconds=1),
        ).execute(
            command=["python3", "-c", _RECORD_PIDS, str(pid_file)],
            timeout=TIMEOUT,
        )
        took = time.monotonic() - started

        assert "command_pid" in seen, "the command never recorded its pids"
        assert took < PROMPT_SECONDS, (
            f"the job ran {took:.1f}s, to its timeout, after its supervisor "
            "was killed"
        )
        assert result.timed_out is False
        assert result.exit_code == -int(signal.SIGKILL)
        assert _wait_until_gone(seen["command_pid"])
    finally:
        if "command_pid" in seen:
            with contextlib.suppress(ProcessLookupError):
                os.kill(seen["command_pid"], signal.SIGKILL)


def test_a_command_that_leaves_a_child_holding_its_pipes_does_not_hold_the_job(
    tmp_path: Path,
) -> None:
    """
    The command exits with code 0 and leaves a child that inherited
    stdout and stderr. The supervisor ends with the command, but the
    pipes stay open, so the owner never reads end of file from them. The
    job has to end when the supervisor does, succeeded, with the child
    killed, and not wait for the timeout and be reported as timed out.
    """
    pid_file = tmp_path / "child_pid"

    try:
        started = time.monotonic()
        result = JobExecutionService(
            termination_grace_period=timedelta(seconds=1),
        ).execute(
            command=["python3", "-c", _LEAVE_A_CHILD, str(pid_file)],
            timeout=TIMEOUT,
        )
        took = time.monotonic() - started

        assert took < PROMPT_SECONDS, (
            f"the job ran {took:.1f}s, to its timeout, because a child of "
            "the command holds its pipes"
        )
        assert result.timed_out is False
        assert result.succeeded is True
        assert _wait_until_gone(int(pid_file.read_text()))
    finally:
        if pid_file.exists() and pid_file.stat().st_size > 0:
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
