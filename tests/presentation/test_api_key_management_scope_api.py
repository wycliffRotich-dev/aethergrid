from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from app.domain.entities.api_key import ApiKey
from app.domain.value_objects.api_key_scope import KEYS_MANAGE
from app.presentation.api import app
from app.presentation.auth import require_api_key


def _act_as(caller: ApiKey) -> TestClient:
    app.dependency_overrides[require_api_key] = lambda: caller
    return TestClient(app)


def test_unscoped_key_cannot_issue_a_key() -> None:
    caller, _ = ApiKey.issue(label="plain")
    client = _act_as(caller)

    response = client.post("/api-keys", json={"label": "new-key"})

    assert response.status_code == 403
    assert "keys:manage" in response.json()["detail"]


def test_scoped_key_can_issue_a_key() -> None:
    caller, _ = ApiKey.issue(
        label="admin",
        scopes=frozenset({KEYS_MANAGE}),
    )
    client = _act_as(caller)

    response = client.post("/api-keys", json={"label": "new-key"})

    assert response.status_code == 201


def test_unscoped_key_cannot_revoke_a_key() -> None:
    caller, _ = ApiKey.issue(label="plain")
    client = _act_as(caller)

    target, _ = ApiKey.issue(label="target")

    response = client.post(f"/api-keys/{target.id}/revoke")

    assert response.status_code == 403
    assert "keys:manage" in response.json()["detail"]


def test_denial_is_logged_with_caller_and_missing_scope_on_issue(
    caplog,
) -> None:
    caller, _ = ApiKey.issue(label="plain")
    client = _act_as(caller)

    with caplog.at_level(logging.WARNING):
        client.post("/api-keys", json={"label": "new-key"})

    assert str(caller.id) in caplog.text
    assert "keys:manage" in caplog.text


def test_denial_is_logged_with_caller_and_missing_scope_on_revoke(
    caplog,
) -> None:
    caller, _ = ApiKey.issue(label="plain")
    client = _act_as(caller)

    target, _ = ApiKey.issue(label="target")

    with caplog.at_level(logging.WARNING):
        client.post(f"/api-keys/{target.id}/revoke")

    assert str(caller.id) in caplog.text
    assert "keys:manage" in caplog.text
