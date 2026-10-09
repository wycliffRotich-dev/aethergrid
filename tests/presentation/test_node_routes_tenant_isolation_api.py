from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.domain.entities.tenant import Tenant
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.tenant_id import TenantId
from app.presentation.api import app
from app.presentation.auth import require_api_key
from app.presentation.dependencies import (
    _tenant_repository,
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


def _offline_since() -> datetime:
    return datetime.now(UTC) - timedelta(minutes=5)


def _masked(response, node_id: NodeId) -> str:
    return response.text.replace(str(node_id), "<id>")


def _snapshot(node):
    return (
        node.last_seen_at,
        node.draining,
        node.available.cpu_cores,
        node.available.memory_mib,
        node.available.vram_mib,
    )


@pytest.fixture
def tenant_a() -> TenantId:
    return _new_tenant()


@pytest.fixture
def tenant_b() -> TenantId:
    return _new_tenant()


@pytest.mark.parametrize(
    ("method", "template", "owner_status"),
    [
        ("GET", "/nodes/{id}", 200),
        ("POST", "/nodes/{id}/heartbeat", 200),
        ("POST", "/nodes/{id}/drain", 200),
        ("DELETE", "/nodes/{id}", 409),
    ],
)
def test_another_tenants_node_answers_like_a_missing_one(
    tenant_a, tenant_b, method, template, owner_status
) -> None:
    repository = get_node_repository()
    node = make_node(tenant_id=tenant_a)
    repository.save(node)
    before = _snapshot(repository.get_by_id(node.id, tenant_a))
    missing_id = NodeId.new()

    client = _as(tenant_b)
    foreign = client.request(method, template.format(id=node.id))
    missing = client.request(method, template.format(id=missing_id))

    assert foreign.status_code == 404
    assert foreign.status_code == missing.status_code
    assert _masked(foreign, node.id) == _masked(missing, missing_id)

    stored = repository.get_by_id(node.id, tenant_a)
    assert stored is not None
    assert _snapshot(stored) == before

    owner = _as(tenant_a).request(method, template.format(id=node.id))
    assert owner.status_code == owner_status


def test_another_tenants_offline_node_is_not_removed(
    tenant_a, tenant_b
) -> None:
    repository = get_node_repository()
    node = make_node(tenant_id=tenant_a, last_seen_at=_offline_since())
    repository.save(node)

    foreign = _as(tenant_b).delete(f"/nodes/{node.id}")

    assert foreign.status_code == 404
    assert repository.get_by_id(node.id, tenant_a) is not None

    owner = _as(tenant_a).delete(f"/nodes/{node.id}")

    assert owner.status_code == 204
    assert repository.get_by_id(node.id, tenant_a) is None


def test_list_nodes_returns_only_the_callers_tenant(
    tenant_a, tenant_b
) -> None:
    repository = get_node_repository()
    node_a = make_node(tenant_id=tenant_a)
    node_b = make_node(tenant_id=tenant_b)
    repository.save(node_a)
    repository.save(node_b)

    ids_a = {n["id"] for n in _as(tenant_a).get("/nodes").json()["nodes"]}
    ids_b = {n["id"] for n in _as(tenant_b).get("/nodes").json()["nodes"]}

    assert ids_a == {str(node_a.id)}
    assert ids_b == {str(node_b.id)}


def test_list_offline_nodes_returns_only_the_callers_tenant(
    tenant_a, tenant_b
) -> None:
    repository = get_node_repository()
    node_a = make_node(tenant_id=tenant_a, last_seen_at=_offline_since())
    node_b = make_node(tenant_id=tenant_b, last_seen_at=_offline_since())
    repository.save(node_a)
    repository.save(node_b)

    body_a = _as(tenant_a).get("/nodes/offline").json()["nodes"]
    body_b = _as(tenant_b).get("/nodes/offline").json()["nodes"]

    assert {n["id"] for n in body_a} == {str(node_a.id)}
    assert {n["id"] for n in body_b} == {str(node_b.id)}


@pytest.fixture
def fleet(tenant_a, tenant_b):
    """
    Tenant A owns two nodes: one alive with 3 cores and 1024 MiB
    allocated, one offline. Tenant B owns one small alive node.
    The numbers differ everywhere, so a view that leaked across
    tenants, or returned nothing, would fail.
    """
    repository = get_node_repository()
    busy = make_node(tenant_id=tenant_a)
    busy.allocate(
        ResourceRequirements(cpu_cores=3, memory_mib=1024, vram_mib=0)
    )
    offline = make_node(tenant_id=tenant_a, last_seen_at=_offline_since())
    small = make_node(
        tenant_id=tenant_b,
        capacity=ResourceRequirements(
            cpu_cores=2,
            memory_mib=1024,
            vram_mib=0,
        ),
    )
    for node in (busy, offline, small):
        repository.save(node)
    return tenant_a, tenant_b


def test_cluster_health_counts_only_the_callers_tenant(fleet) -> None:
    tenant_a, tenant_b = fleet

    assert _as(tenant_a).get("/cluster/health").json() == {
        "total_nodes": 2,
        "alive_nodes": 1,
        "offline_nodes": 1,
    }
    assert _as(tenant_b).get("/cluster/health").json() == {
        "total_nodes": 1,
        "alive_nodes": 1,
        "offline_nodes": 0,
    }


def test_cluster_capacity_sums_only_the_callers_tenant(fleet) -> None:
    tenant_a, tenant_b = fleet

    assert _as(tenant_a).get("/cluster/capacity").json() == {
        "cpu_cores": 13,
        "memory_mib": 31744,
        "vram_mib": 16384,
    }
    assert _as(tenant_b).get("/cluster/capacity").json() == {
        "cpu_cores": 2,
        "memory_mib": 1024,
        "vram_mib": 0,
    }


def test_cluster_utilization_sums_only_the_callers_tenant(fleet) -> None:
    tenant_a, tenant_b = fleet

    assert _as(tenant_a).get("/cluster/utilization").json() == {
        "cpu_cores": 3,
        "memory_mib": 1024,
        "vram_mib": 0,
    }
    assert _as(tenant_b).get("/cluster/utilization").json() == {
        "cpu_cores": 0,
        "memory_mib": 0,
        "vram_mib": 0,
    }
