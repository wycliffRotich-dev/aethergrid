from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.domain.entities.tenant import DEFAULT_TENANT_ID, Tenant
from app.domain.value_objects.node_id import NodeId
from app.presentation.api import app
from app.presentation.auth import require_api_key
from app.presentation.dependencies import (
    _tenant_repository,
    get_node_repository,
)
from tests.support.api_keys import make_api_key


@pytest.fixture
def created_node_ids():
    """
    Collects the nodes a test creates through the API and removes
    them afterwards, because the node repository is shared across
    tests. Also clears the auth override the test installed.
    """
    node_ids: list[NodeId] = []

    yield node_ids

    app.dependency_overrides.pop(require_api_key, None)
    for node_id in node_ids:
        node = get_node_repository().get_by_id_across_tenants(node_id)
        if node is not None:
            get_node_repository().delete(node_id, node.tenant_id)


def test_a_created_node_belongs_to_the_callers_tenant(
    created_node_ids,
) -> None:
    tenant = Tenant.create(f"t-{uuid.uuid4().hex[:8]}")
    _tenant_repository.save(tenant)
    caller, _ = make_api_key(label="caller", tenant_id=tenant.id)
    app.dependency_overrides[require_api_key] = lambda: caller
    client = TestClient(app)

    response = client.post(
        "/nodes",
        json={
            "cpu_cores": 4,
            "memory_mib": 8192,
            "vram_mib": 0,
            "name": "tenant-node",
        },
    )

    assert response.status_code == 201
    node_id = NodeId.from_string(response.json()["id"])
    created_node_ids.append(node_id)

    node = get_node_repository().get_by_id(node_id, tenant.id)
    assert node is not None
    assert node.tenant_id == tenant.id
    assert node.tenant_id != DEFAULT_TENANT_ID


def test_a_tenant_in_the_request_body_is_ignored(
    created_node_ids,
) -> None:
    """
    ADR 0064, point 3: the tenant comes from the credential and
    never from the request. A body that names another tenant must
    not move the node there.
    """
    callers_tenant = Tenant.create(f"t-{uuid.uuid4().hex[:8]}")
    other_tenant = Tenant.create(f"t-{uuid.uuid4().hex[:8]}")
    _tenant_repository.save(callers_tenant)
    _tenant_repository.save(other_tenant)
    caller, _ = make_api_key(label="caller", tenant_id=callers_tenant.id)
    app.dependency_overrides[require_api_key] = lambda: caller
    client = TestClient(app)

    response = client.post(
        "/nodes",
        json={
            "cpu_cores": 4,
            "memory_mib": 8192,
            "vram_mib": 0,
            "tenant_id": str(other_tenant.id),
        },
    )

    assert response.status_code == 201
    node_id = NodeId.from_string(response.json()["id"])
    created_node_ids.append(node_id)

    node = get_node_repository().get_by_id(node_id, callers_tenant.id)
    assert node is not None
    assert node.tenant_id == callers_tenant.id
    assert node.tenant_id != other_tenant.id
