from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from app.domain.entities.api_key import ApiKey
from app.domain.value_objects.api_key_scope import JOBS_EXECUTE
from app.presentation.api import app
from app.presentation.auth import require_api_key
from tests.support.api_keys import make_api_key

RESOURCES = {"cpu_cores": 1, "memory_mib": 128, "vram_mib": 0}
COMMAND = ["python", "train.py"]


def _act_as(caller: ApiKey) -> TestClient:
    app.dependency_overrides[require_api_key] = lambda: caller
    return TestClient(app)


def test_unscoped_key_can_create_a_resource_only_job() -> None:
    caller, _ = make_api_key(label="plain")
    client = _act_as(caller)

    response = client.post("/jobs", json=RESOURCES)

    assert response.status_code == 201


def test_unscoped_key_cannot_set_a_command() -> None:
    caller, _ = make_api_key(label="plain")
    client = _act_as(caller)

    response = client.post(
        "/jobs", json={**RESOURCES, "command": COMMAND}
    )

    assert response.status_code == 403
    assert "jobs:execute" in response.json()["detail"]
    assert client.get("/jobs").json()["jobs"] == []


def test_scoped_key_can_set_a_command() -> None:
    caller, _ = make_api_key(
        label="runner",
        scopes=frozenset({JOBS_EXECUTE}),
    )
    client = _act_as(caller)

    response = client.post(
        "/jobs", json={**RESOURCES, "command": COMMAND}
    )

    assert response.status_code == 201


def test_denial_is_logged_with_caller_and_missing_scope(
    caplog,
) -> None:
    caller, _ = make_api_key(label="plain")
    client = _act_as(caller)

    with caplog.at_level(logging.WARNING):
        client.post("/jobs", json={**RESOURCES, "command": COMMAND})

    assert str(caller.id) in caplog.text
    assert "jobs:execute" in caplog.text
