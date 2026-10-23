from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.domain.entities.tenant import Tenant
from app.domain.entities.worker import Worker
from app.domain.enums.worker_status import WorkerStatus
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId
from app.presentation.api import app
from app.presentation.auth import require_api_key
from app.presentation.dependencies import (
    _tenant_repository,
    _worker_repository,
    get_node_repository,
)
from tests.support.api_keys import make_api_key
from tests.support.nodes import make_node
from tests.support.workers import make_worker


def _new_tenant() -> TenantId:
    tenant = Tenant.create(f"t-{uuid.uuid4().hex[:8]}")
    _tenant_repository.save(tenant)
    return tenant.id


def _as(tenant_id: TenantId) -> TestClient:
    caller, _ = make_api_key(label="caller", tenant_id=tenant_id)
    app.dependency_overrides[require_api_key] = lambda: caller
    return TestClient(app)


def _offline_worker(
    tenant_id: TenantId, last_seen_at: datetime
) -> Worker:
    node = make_node(tenant_id=tenant_id)
    get_node_repository().save(node)
    worker = make_worker(node=node, last_seen_at=last_seen_at)
    worker.offline()
    _worker_repository.save(worker)
    return worker


@pytest.fixture
def tenant_a() -> TenantId:
    return _new_tenant()


@pytest.fixture
def tenant_b() -> TenantId:
    return _new_tenant()


def test_another_tenants_worker_cannot_be_heartbeated(
    tenant_a: TenantId, tenant_b: TenantId
) -> None:
    stale = datetime.now(UTC) - timedelta(seconds=30)
    worker = _offline_worker(tenant_a, stale)

    foreign = _as(tenant_b).post(f"/workers/{worker.id}/heartbeat")
    missing_id = WorkerId.new()
    missing = _as(tenant_b).post(f"/workers/{missing_id}/heartbeat")

    assert foreign.status_code == 404
    assert foreign.status_code == missing.status_code
    assert foreign.text.replace(str(worker.id), "<id>") == (
        missing.text.replace(str(missing_id), "<id>")
    )

    stored = _worker_repository.get_by_id(worker.id, worker.tenant_id)
    assert stored is not None
    assert stored.last_seen_at == stale
    assert stored.status is WorkerStatus.OFFLINE


def test_a_worker_can_still_be_heartbeated_by_its_own_tenant(
    tenant_a: TenantId,
) -> None:
    stale = datetime.now(UTC) - timedelta(seconds=30)
    worker = _offline_worker(tenant_a, stale)

    response = _as(tenant_a).post(f"/workers/{worker.id}/heartbeat")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(worker.id)
    assert body["status"] == "IDLE"
    stored = _worker_repository.get_by_id(worker.id, worker.tenant_id)
    assert stored is not None
    assert stored.last_seen_at > stale
