from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# A command that starts a child of its own, records the child's pid in
# the file named by its first argument, and then waits.
_SPAWN_A_CHILD = (
    "import subprocess, sys, time; "
    "child = subprocess.Popen(['sleep', '60']); "
    "open(sys.argv[1], 'w').write(str(child.pid)); "
    "time.sleep(60)"
)

# The owner of the job: a process that runs the command through
# JobExecutionService, as the agent and the API process do. Its first
# argument is the pid file and its second is the command's script.
_OWNER = (
    "import sys; "
    "from datetime import timedelta; "
    "from app.application.services.job_execution_service import "
    "JobExecutionService; "
    "JobExecutionService().execute("
    "command=['python3', '-c', sys.argv[2], sys.argv[1]], "
    "timeout=timedelta(seconds=60))"
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


def test_a_job_does_not_outlive_an_owner_that_is_killed(
    tmp_path: Path,
) -> None:
    """
    ADR 0080. The owner is killed outright, so none of its cleanup
    code runs, and the command it started must still end.
    """
    pid_file = tmp_path / "child.pid"
    owner = subprocess.Popen(
        [sys.executable, "-c", _OWNER, str(pid_file), _SPAWN_A_CHILD],
        cwd=REPO_ROOT,
        start_new_session=True,
    )
    child_pid = None
    group_id = None

    try:
        child_pid = _wait_for_pid(pid_file)
        assert child_pid is not None, "the command never started its child"
        group_id = os.getpgid(child_pid)

        owner.kill()
        owner.wait(timeout=5)

        assert _wait_until_gone(child_pid), (
            f"the child of the job (pid {child_pid}) outlived its owner, "
            "which was killed with SIGKILL"
        )
    finally:
        if group_id is not None and group_id != os.getpgrp():
            with contextlib.suppress(ProcessLookupError):
                os.killpg(group_id, signal.SIGKILL)
        if child_pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(child_pid, signal.SIGKILL)
        if owner.poll() is None:
            owner.kill()
            owner.wait()
