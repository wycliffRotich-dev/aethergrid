from __future__ import annotations

import dataclasses
import logging

from fastapi.testclient import TestClient

from app.domain.entities.api_key import ApiKey
from app.domain.value_objects.api_key_id import ApiKeyId
from app.domain.value_objects.api_key_scope import KEYS_MANAGE
from app.presentation.api import app
from app.presentation.auth import require_api_key
from app.presentation.dependencies import _api_key_repository


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
    # production callers are always persisted rows (auth loads them
    # from the repository); issued_by has an FK to api_keys(id)
    _api_key_repository.save(caller)
    client = _act_as(caller)

    response = client.post("/api-keys", json={"label": "new-key"})

    assert response.status_code == 201


def test_unscoped_key_cannot_revoke_a_key() -> None:
    caller, _ = ApiKey.issue(label="plain")
    client = _act_as(caller)

    target, _ = ApiKey.issue(label="target")
    _api_key_repository.save(target)

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
    _api_key_repository.save(target)

    with caplog.at_level(logging.WARNING):
        client.post(f"/api-keys/{target.id}/revoke")

    assert str(caller.id) in caplog.text
    assert "keys:manage" in caplog.text


def test_owner_can_revoke_a_key_it_issued_without_keys_manage() -> None:
    # The whole point of ADR 0056: ownership alone, with no
    # keys:manage at all, is sufficient to revoke a key this
    # caller issued.
    owner, _ = ApiKey.issue(
        label="owner",
        scopes=frozenset({KEYS_MANAGE}),
    )
    _api_key_repository.save(owner)
    client = _act_as(owner)

    issue_response = client.post(
        "/api-keys", json={"label": "sub-key"}
    )
    assert issue_response.status_code == 201
    issued_id = issue_response.json()["id"]

    # Re-authenticate as the same key identity but with
    # scopes stripped, proving the second revoke call
    # succeeds on ownership alone, not because keys:manage
    # happens to still be present. dataclasses.replace keeps
    # every other field, including id, exactly as issued --
    # no manual field mutation, no entity built outside
    # ApiKey.issue().
    owner_without_scope = dataclasses.replace(
        owner, scopes=frozenset()
    )
    client = _act_as(owner_without_scope)

    response = client.post(f"/api-keys/{issued_id}/revoke")

    assert response.status_code == 204


def test_non_owner_without_keys_manage_cannot_revoke_someone_elses_key() -> (
    None
):
    issuer, _ = ApiKey.issue(
        label="issuer",
        scopes=frozenset({KEYS_MANAGE}),
    )
    _api_key_repository.save(issuer)
    client = _act_as(issuer)

    issue_response = client.post(
        "/api-keys", json={"label": "owned-key"}
    )
    assert issue_response.status_code == 201
    target_id = issue_response.json()["id"]

    stranger, _ = ApiKey.issue(label="stranger")
    _api_key_repository.save(stranger)
    client = _act_as(stranger)

    response = client.post(f"/api-keys/{target_id}/revoke")

    assert response.status_code == 403
    assert "keys:manage" in response.json()["detail"]


def test_keys_manage_can_revoke_a_legacy_key_with_no_issuer() -> None:
    legacy_key, _ = ApiKey.issue(label="predates-adr-0056")
    _api_key_repository.save(legacy_key)
    assert legacy_key.issued_by is None

    admin, _ = ApiKey.issue(
        label="admin",
        scopes=frozenset({KEYS_MANAGE}),
    )
    _api_key_repository.save(admin)
    client = _act_as(admin)

    response = client.post(f"/api-keys/{legacy_key.id}/revoke")

    assert response.status_code == 204


def test_non_owner_cannot_revoke_a_legacy_key_with_no_issuer() -> None:
    legacy_key, _ = ApiKey.issue(label="predates-adr-0056")
    _api_key_repository.save(legacy_key)

    stranger, _ = ApiKey.issue(label="stranger")
    _api_key_repository.save(stranger)
    client = _act_as(stranger)

    response = client.post(f"/api-keys/{legacy_key.id}/revoke")

    assert response.status_code == 403


def test_caller_can_list_keys_it_issued_without_keys_manage() -> None:
    owner, _ = ApiKey.issue(
        label="owner",
        scopes=frozenset({KEYS_MANAGE}),
    )
    _api_key_repository.save(owner)
    client = _act_as(owner)

    issue_response = client.post(
        "/api-keys", json={"label": "child-one"}
    )
    assert issue_response.status_code == 201
    child_id = issue_response.json()["id"]

    # Re-authenticate as the same identity with no scopes,
    # proving the list call succeeds on self-view alone.
    owner_without_scope = dataclasses.replace(
        owner, scopes=frozenset()
    )
    client = _act_as(owner_without_scope)

    response = client.get(f"/api-keys/{owner.id}/issued")

    assert response.status_code == 200
    issued_ids = {entry["id"] for entry in response.json()["issued"]}
    assert child_id in issued_ids


def test_keys_manage_can_list_someone_elses_issued_keys() -> None:
    owner, _ = ApiKey.issue(label="owner")
    _api_key_repository.save(owner)
    client = _act_as(owner)
    # owner itself has no keys:manage, so it cannot issue over
    # HTTP; seed its child directly instead.
    child, _ = ApiKey.issue(label="child", issued_by=owner.id)
    _api_key_repository.save(child)

    admin, _ = ApiKey.issue(
        label="admin",
        scopes=frozenset({KEYS_MANAGE}),
    )
    _api_key_repository.save(admin)
    client = _act_as(admin)

    response = client.get(f"/api-keys/{owner.id}/issued")

    assert response.status_code == 200
    issued_ids = {entry["id"] for entry in response.json()["issued"]}
    assert str(child.id) in issued_ids


def test_non_owner_without_keys_manage_cannot_list_someone_elses_issued_keys() -> (
    None
):
    owner, _ = ApiKey.issue(label="owner")
    _api_key_repository.save(owner)

    stranger, _ = ApiKey.issue(label="stranger")
    _api_key_repository.save(stranger)
    client = _act_as(stranger)

    response = client.get(f"/api-keys/{owner.id}/issued")

    assert response.status_code == 403
    assert "keys:manage" in response.json()["detail"]


def test_listing_issued_keys_includes_revoked_ones() -> None:
    owner, _ = ApiKey.issue(label="owner")
    _api_key_repository.save(owner)

    child, _ = ApiKey.issue(label="revoked-child", issued_by=owner.id)
    child.revoke()
    _api_key_repository.save(child)

    client = _act_as(owner)

    response = client.get(f"/api-keys/{owner.id}/issued")

    assert response.status_code == 200
    entries = {
        entry["id"]: entry for entry in response.json()["issued"]
    }
    assert str(child.id) in entries
    assert entries[str(child.id)]["revoked_at"] is not None


def test_listing_issued_keys_for_a_nonexistent_id_is_404() -> None:
    caller, _ = ApiKey.issue(
        label="caller",
        scopes=frozenset({KEYS_MANAGE}),
    )
    _api_key_repository.save(caller)
    client = _act_as(caller)

    missing_id = ApiKeyId.new()

    response = client.get(f"/api-keys/{missing_id}/issued")

    assert response.status_code == 404
