from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.domain.entities.api_key import ApiKey
from app.domain.entities.tenant import Tenant
from app.domain.value_objects.api_key_id import ApiKeyId
from app.domain.value_objects.api_key_scope import KEYS_MANAGE
from app.presentation.api import app
from app.presentation.auth import require_api_key
from app.presentation.dependencies import (
    _api_key_repository,
    _tenant_repository,
)
from tests.support.api_keys import make_api_key


def _act_as(caller: ApiKey) -> TestClient:
    app.dependency_overrides[require_api_key] = lambda: caller
    return TestClient(app)


def _new_tenant() -> Tenant:
    tenant = Tenant.create(f"t-{uuid.uuid4().hex[:8]}")
    _tenant_repository.save(tenant)
    return tenant


def test_foreign_admin_cannot_revoke_a_key_in_another_tenant() -> None:
    tenant_a = _new_tenant()
    tenant_b = _new_tenant()
    target, _ = make_api_key(label="target", tenant_id=tenant_a.id)
    _api_key_repository.save(target)
    foreign_admin, _ = make_api_key(
        label="foreign-admin",
        scopes=frozenset({KEYS_MANAGE}),
        tenant_id=tenant_b.id,
    )
    _api_key_repository.save(foreign_admin)
    client = _act_as(foreign_admin)

    response = client.post(f"/api-keys/{target.id}/revoke")

    assert response.status_code == 404
    stored = _api_key_repository.get_by_id(target.id, tenant_a.id)
    assert stored is not None
    assert stored.is_active()


def test_foreign_caller_without_the_scope_gets_404_not_403() -> None:
    tenant_a = _new_tenant()
    tenant_b = _new_tenant()
    target, _ = make_api_key(label="target", tenant_id=tenant_a.id)
    _api_key_repository.save(target)
    foreign_caller, _ = make_api_key(
        label="foreign-caller",
        tenant_id=tenant_b.id,
    )
    _api_key_repository.save(foreign_caller)
    client = _act_as(foreign_caller)

    response = client.post(f"/api-keys/{target.id}/revoke")

    assert response.status_code == 404


def test_foreign_admin_cannot_list_another_tenants_issued_keys() -> None:
    tenant_a = _new_tenant()
    tenant_b = _new_tenant()
    issuer, _ = make_api_key(label="issuer", tenant_id=tenant_a.id)
    _api_key_repository.save(issuer)
    foreign_admin, _ = make_api_key(
        label="foreign-admin",
        scopes=frozenset({KEYS_MANAGE}),
        tenant_id=tenant_b.id,
    )
    _api_key_repository.save(foreign_admin)
    client = _act_as(foreign_admin)

    response = client.get(f"/api-keys/{issuer.id}/issued")

    assert response.status_code == 404


def test_a_foreign_key_is_indistinguishable_from_a_missing_one() -> None:
    tenant_a = _new_tenant()
    tenant_b = _new_tenant()
    target, _ = make_api_key(label="target", tenant_id=tenant_a.id)
    _api_key_repository.save(target)
    foreign_admin, _ = make_api_key(
        label="foreign-admin",
        scopes=frozenset({KEYS_MANAGE}),
        tenant_id=tenant_b.id,
    )
    _api_key_repository.save(foreign_admin)
    client = _act_as(foreign_admin)
    missing_id = ApiKeyId.new()

    foreign = client.post(f"/api-keys/{target.id}/revoke")
    missing = client.post(f"/api-keys/{missing_id}/revoke")

    assert foreign.status_code == missing.status_code == 404
    # The message names the id that was asked about, so compare
    # the two bodies with that id removed.
    assert foreign.json()["detail"].replace(
        str(target.id), "<id>"
    ) == missing.json()["detail"].replace(str(missing_id), "<id>")


def test_a_key_issued_over_http_lands_in_the_issuers_tenant() -> None:
    tenant_b = _new_tenant()
    admin, _ = make_api_key(
        label="admin",
        scopes=frozenset({KEYS_MANAGE}),
        tenant_id=tenant_b.id,
    )
    _api_key_repository.save(admin)
    client = _act_as(admin)

    response = client.post("/api-keys", json={"label": "new-key"})

    assert response.status_code == 201
    issued_id = ApiKeyId(response.json()["id"])
    stored = _api_key_repository.get_by_id(issued_id, tenant_b.id)
    assert stored is not None
    assert stored.tenant_id == tenant_b.id
    assert stored.issued_by == admin.id
