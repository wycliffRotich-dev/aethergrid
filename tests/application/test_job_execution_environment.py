from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.application.services.job_execution_service import (
    JobExecutionService,
)

_PRINT_THE_ENVIRONMENT = "import json, os; print(json.dumps(dict(os.environ)))"

# One name is unrelated to this project on purpose. A rule that only
# strips known prefixes would let it through, and an allowlist does not.
_SECRETS = {
    "NEUROMESH_DATABASE_URL": "postgresql://leak-marker-url",
    "NEUROMESH_DATABASE_PASSWORD_FILE": "/run/secrets/leak-marker-file",
    "AETHERGRID_API_KEY": "leak-marker-api-key",
    "AN_UNRELATED_SECRET": "leak-marker-unrelated",
}


def _environment_seen_by_a_command(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, str]:
    for name, value in _SECRETS.items():
        monkeypatch.setenv(name, value)

    result = JobExecutionService().execute(
        command=["python3", "-c", _PRINT_THE_ENVIRONMENT],
        timeout=timedelta(seconds=15),
    )

    assert result.succeeded, result.stderr

    seen = json.loads(result.stdout)
    assert isinstance(seen, dict)

    return seen


def test_a_command_does_not_inherit_the_executors_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _environment_seen_by_a_command(monkeypatch)

    leaked = sorted(name for name in _SECRETS if name in seen)

    assert leaked == [], f"the command could read: {leaked}"


def test_a_command_still_finds_its_programs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _environment_seen_by_a_command(monkeypatch)

    assert "PATH" in seen
