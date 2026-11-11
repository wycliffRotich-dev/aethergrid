"""
Close a process to the commands it starts (ADR 0095).

The executor holds credentials in its environment. A job's command is its
child and runs as the same user, so on Linux it could read
/proc/<pid>/environ of the executor. A process that is not dumpable keeps
those files closed to its children.

Linux resets the flag when a process starts another program, so each
process that holds credentials calls this itself. This module uses the
standard library only, because the job supervisor starts once for every
job.
"""

from __future__ import annotations

import ctypes
import os
import sys

PR_SET_DUMPABLE = 4


def make_unreadable_through_proc() -> None:
    """
    Stop this process's children from reading its /proc entry.

    Only Linux has this protection, so nothing is done elsewhere. A kernel
    that refuses the call raises, and the process does not start: a
    process that cannot close its own entry must not run jobs.
    """
    if sys.platform != "linux":
        return

    libc = ctypes.CDLL(None, use_errno=True)

    if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
