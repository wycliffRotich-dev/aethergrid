from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.domain.entities.tenant import Tenant
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.tenant_id import TenantId
from app.presentation.api import app
from app.presentation.auth import require_api_key
from app.presentation.dependencies import (
    _tenant_repository,
    _worker_repository,
    get_node_repository,
)
from tests.support.api_keys import make_api_key
from tests.support.nodes import make_node


def _new_tenant() -> TenantId:
    tenant = Tenant.create(f"t-{uuid.uuid4().hex[:8]}")
    _tenant_repository.save(tenant)
    return tenant.id


def _as(tenant_id: TenantId) -> TestClient:
    caller, _ = make_api_key(label="caller", tenant_id=tenant_id)
    app.dependency_overrides[require_api_key] = lambda: caller
    return TestClient(app)


def test_registering_a_worker_on_another_tenants_node_answers_404() -> None:
    tenant_a = _new_tenant()
    tenant_b = _new_tenant()
    node = make_node(tenant_id=tenant_a)
    get_node_repository().save(node)

    foreign = _as(tenant_b).post("/workers", json={"node_id": str(node.id)})
    missing = _as(tenant_b).post(
        "/workers", json={"node_id": str(NodeId.new())}
    )

    assert foreign.status_code == 404
    assert foreign.status_code == missing.status_code
    assert foreign.json() == missing.json()
    assert _worker_repository.list() == []


def test_the_owning_tenant_can_still_register_a_worker() -> None:
    tenant_a = _new_tenant()
    node = make_node(tenant_id=tenant_a)
    get_node_repository().save(node)

    response = _as(tenant_a).post("/workers", json={"node_id": str(node.id)})

    assert response.status_code == 201
    assert response.json()["status"] == "IDLE"
    assert len(_worker_repository.list()) == 1
