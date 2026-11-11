"""
Start a job's command and end it when its owner dies (ADR 0080).

JobExecutionService starts this module in a new session, so the module
leads a process group of its own. It starts the command in that group
and waits for it. It also holds the read end of a pipe whose write end
only the owner holds. When the owner dies, by any means, the kernel
closes the write end, the module reads end of file and sends SIGKILL to
the group, which holds the command and what it started.

The module starts the command itself, so there is no moment when the
command runs and nothing watches its owner. It ends the way the command
did, with the same exit code or the same signal, so the owner sees the
command's own result. A command that cannot be started is reported on
the status pipe, because no exit code can be told apart from a real one.
It uses the standard library only, because it starts once for every job.

Usage: python -m app.application.services.job_supervisor WATCH_FD
STATUS_FD -- COMMAND...
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Mapping

from app.application.process_hardening import make_unreadable_through_proc

USAGE_EXIT_CODE = 2
LAUNCH_FAILED_EXIT_CODE = 127


# Names of extra variables the operator chose to pass to every job
# (ADR 0095), comma separated. The setting is not passed itself.
JOB_ENV_PASSTHROUGH_SETTING = "NEUROMESH_JOB_ENV_PASSTHROUGH"

# The only variables a job's command receives from the executor
# (ADR 0095). Anything else, a credential included, stays behind.
JOB_ENVIRONMENT_ALLOWLIST = (
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "TMPDIR",
    "TZ",
)


def job_environment(source: Mapping[str, str]) -> dict[str, str]:
    """
    The environment a job's command starts with.

    Built from an allowlist and not by removing known names, so a
    secret that nobody thought to list never reaches the command.
    """
    named = (
        entry.strip()
        for entry in source.get(JOB_ENV_PASSTHROUGH_SETTING, "").split(",")
    )
    allowed = {*JOB_ENVIRONMENT_ALLOWLIST, *(name for name in named if name)}

    return {name: source[name] for name in sorted(allowed) if name in source}


def _kill_own_group() -> None:
    os.killpg(os.getpgrp(), signal.SIGKILL)


def _watch(watch_fd: int) -> None:
    """
    Kill the group when the owner's end of the pipe closes.

    A read that fails is treated as the same thing. If the pipe cannot
    be read, the owner cannot be watched, and the safe answer is to
    end the group.
    """
    while True:
        try:
            data = os.read(watch_fd, 1)
        except OSError:
            data = b""

        if not data:
            _kill_own_group()
            return


def _report_launch_failure(status_fd: int, error: OSError) -> None:
    report = {
        "errno": error.errno,
        "strerror": error.strerror,
        "filename": error.filename,
    }

    with os.fdopen(status_fd, "w", encoding="utf-8") as status:
        json.dump(report, status)


def _end_like(returncode: int) -> int:
    """
    End the way the command did.

    An exit code is returned as it is. A death by a signal is repeated
    on this process, so the owner reads the same negated signal number.
    """
    if returncode >= 0:
        return returncode

    number = -returncode

    try:
        signal.signal(number, signal.SIG_DFL)
    except (OSError, ValueError):
        pass  # SIGKILL and SIGSTOP have no handler to reset.

    os.kill(os.getpid(), number)

    return 128 + number


def main(argv: list[str]) -> int:
    make_unreadable_through_proc()

    if len(argv) < 5 or argv[3] != "--":
        print(
            "usage: job_supervisor WATCH_FD STATUS_FD -- COMMAND...",
            file=sys.stderr,
        )
        return USAGE_EXIT_CODE

    watch_fd = int(argv[1])
    status_fd = int(argv[2])
    command = argv[4:]

    # SIGKILL goes to this process's own group. If another process led
    # the group, that would end processes that are not this job's.
    if os.getpgrp() != os.getpid():
        print(
            "job_supervisor must lead its own process group",
            file=sys.stderr,
        )
        return USAGE_EXIT_CODE

    # The owner sends SIGTERM to the whole group. This module must live
    # through it so the command decides what to do. A function handler
    # is used and not SIG_IGN, because an ignored signal stays ignored
    # in a process that is started after, and the command would then
    # stop obeying SIGTERM.
    signal.signal(signal.SIGTERM, lambda signum, frame: None)

    threading.Thread(target=_watch, args=(watch_fd,), daemon=True).start()

    try:
        process = subprocess.Popen(command, env=job_environment(os.environ))
    except OSError as error:
        _report_launch_failure(status_fd, error)
        return LAUNCH_FAILED_EXIT_CODE

    os.close(status_fd)

    return _end_like(process.wait())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
