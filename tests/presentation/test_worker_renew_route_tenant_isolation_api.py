from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.application.services.acquire_lease_service import (
    AcquireLeaseService,
)
from app.domain.entities.lease import Lease
from app.domain.entities.tenant import Tenant
from app.domain.entities.worker import Worker
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId
from app.presentation.api import app
from app.presentation.auth import require_api_key
from app.presentation.dependencies import (
    _job_repository,
    _lease_repository,
    _tenant_repository,
    _worker_repository,
    get_node_repository,
)
from tests.support.api_keys import make_api_key
from tests.support.jobs import make_job
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


def _worker_holding_a_lease(tenant_id: TenantId) -> tuple[Worker, Lease]:
    node = make_node(tenant_id=tenant_id)
    get_node_repository().save(node)
    job = make_job(tenant_id=tenant_id)
    job.queue()
    job.assign_to(node.id)
    _job_repository.save(job)
    worker = make_worker(node=node)
    worker.ready()
    worker.accept(job)
    _worker_repository.save(worker)
    AcquireLeaseService(
        lease_repository=_lease_repository,
    ).execute(worker, job)
    lease = _lease_repository.get_by_worker_id(worker.id, worker.tenant_id)
    assert lease is not None
    return worker, lease


@pytest.fixture
def tenant_a() -> TenantId:
    return _new_tenant()


@pytest.fixture
def tenant_b() -> TenantId:
    return _new_tenant()


def test_another_tenant_cannot_renew_a_lease_even_with_its_real_id(
    tenant_a: TenantId, tenant_b: TenantId
) -> None:
    worker, lease = _worker_holding_a_lease(tenant_a)
    lease_id = lease.id
    expires_before: datetime = lease.expires_at
    body = {"lease_id": str(lease_id)}

    foreign = _as(tenant_b).post(
        f"/workers/{worker.id}/lease/renew", json=body
    )
    missing_id = WorkerId.new()
    missing = _as(tenant_b).post(
        f"/workers/{missing_id}/lease/renew", json=body
    )

    assert foreign.status_code == 404
    assert foreign.status_code == missing.status_code
    assert foreign.text.replace(str(worker.id), "<id>") == (
        missing.text.replace(str(missing_id), "<id>")
    )

    after = _lease_repository.get_by_worker_id(worker.id, worker.tenant_id)
    assert after is not None
    assert after.id == lease_id
    assert after.expires_at == expires_before


def test_a_workers_own_tenant_can_still_renew_its_lease(
    tenant_a: TenantId,
) -> None:
    worker, lease = _worker_holding_a_lease(tenant_a)
    lease_id = lease.id
    expires_before: datetime = lease.expires_at

    response = _as(tenant_a).post(
        f"/workers/{worker.id}/lease/renew",
        json={"lease_id": str(lease_id)},
    )

    assert response.status_code == 200
    after = _lease_repository.get_by_worker_id(worker.id, worker.tenant_id)
    assert after is not None
    assert after.id == lease_id
    assert after.expires_at > expires_before
