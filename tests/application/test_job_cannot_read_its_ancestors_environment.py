"""
ADR 0095. Scrubbing the environment a command starts with is not enough
on Linux: a process of the same user can read /proc/<pid>/environ of its
ancestors. The command must not find the executor's secrets there either.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.application.services.job_execution_service import (
    JobExecutionService,
)

_SECRETS = {
    "LEAK_MARKER_DATABASE_URL": "postgresql://leak-marker-url",
    "AETHERGRID_API_KEY": "leak-marker-api-key",
    "AN_UNRELATED_SECRET": "leak-marker-unrelated",
}

# Walks up the process tree and prints the names of every variable it
# can read from an ancestor's /proc/<pid>/environ.
_READ_ANCESTORS = r"""
import json, os
names = []
pid = os.getppid()
for _ in range(6):
    if pid < 1:
        break
    try:
        data = open(f"/proc/{pid}/environ", "rb").read()
        names += [e.split(b"=", 1)[0].decode() for e in data.split(b"\0") if e]
    except OSError:
        pass
    try:
        pid = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        break
print(json.dumps(names))
"""


def test_a_command_cannot_read_the_executors_secrets_from_proc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in _SECRETS.items():
        monkeypatch.setenv(name, value)

    result = JobExecutionService().execute(
        command=["python3", "-c", _READ_ANCESTORS],
        timeout=timedelta(seconds=15),
    )

    assert result.succeeded, result.stderr

    readable = set(json.loads(result.stdout))
    leaked = sorted(name for name in _SECRETS if name in readable)

    assert leaked == [], f"the command read from an ancestor: {leaked}"
