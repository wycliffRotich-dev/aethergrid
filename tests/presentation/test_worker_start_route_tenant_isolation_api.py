from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.application.services.acquire_lease_service import (
    AcquireLeaseService,
)
from app.domain.entities.tenant import Tenant
from app.domain.entities.worker import Worker
from app.domain.enums.job_status import JobStatus
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


def _worker_holding_a_scheduled_job(tenant_id: TenantId) -> Worker:
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
    return worker


@pytest.fixture
def tenant_a() -> TenantId:
    return _new_tenant()


@pytest.fixture
def tenant_b() -> TenantId:
    return _new_tenant()


def test_another_tenants_worker_cannot_start_a_job(
    tenant_a: TenantId, tenant_b: TenantId
) -> None:
    worker = _worker_holding_a_scheduled_job(tenant_a)
    job_id = worker.running_job.id
    lease_before = _lease_repository.get_by_worker_id(worker.id)
    assert lease_before is not None
    stored_job = _job_repository.get_by_id(job_id, tenant_a)
    assert stored_job.status == JobStatus.SCHEDULED

    foreign = _as(tenant_b).post(
        f"/workers/{worker.id}/jobs/{job_id}/start"
    )
    missing_id = WorkerId.new()
    missing = _as(tenant_b).post(
        f"/workers/{missing_id}/jobs/{job_id}/start"
    )

    assert foreign.status_code == 404
    assert foreign.status_code == missing.status_code
    assert foreign.text.replace(str(worker.id), "<id>") == (
        missing.text.replace(str(missing_id), "<id>")
    )

    stored_worker = _worker_repository.get_by_id(worker.id)
    assert stored_worker is not None
    assert stored_worker.running_job is not None
    assert stored_worker.running_job.id == job_id
    after = _job_repository.get_by_id(job_id, tenant_a)
    assert after.status == JobStatus.SCHEDULED
    lease = _lease_repository.get_by_worker_id(worker.id)
    assert lease is not None
    assert lease.id == lease_before.id
