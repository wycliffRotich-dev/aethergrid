from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.application.services.acquire_lease_service import (
    AcquireLeaseService,
)
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


def _worker_holding_a_leased_job(
    tenant_id: TenantId, *, cancelling: bool = False
) -> tuple[Worker, UUID]:
    node = make_node(tenant_id=tenant_id)
    get_node_repository().save(node)
    job = make_job(tenant_id=tenant_id)
    job.queue()
    job.assign_to(node.id)
    job.start()
    if cancelling:
        job.request_cancellation()
    _job_repository.save(job)
    worker = make_worker(node=node)
    worker.ready()
    worker.accept(job)
    _worker_repository.save(worker)
    lease = AcquireLeaseService(
        lease_repository=_lease_repository,
    ).execute(worker, job)
    return worker, lease.id


@pytest.fixture
def tenant_a() -> TenantId:
    return _new_tenant()


@pytest.fixture
def tenant_b() -> TenantId:
    return _new_tenant()


@pytest.mark.parametrize(
    ("action", "cancelling"),
    [("complete", False), ("fail", False), ("cancel", True)],
)
def test_another_tenants_worker_cannot_report_an_outcome(
    tenant_a: TenantId, tenant_b: TenantId, action: str, cancelling: bool
) -> None:
    worker, lease_id = _worker_holding_a_leased_job(
        tenant_a, cancelling=cancelling
    )
    job_id = worker.running_job.id
    status_before = _job_repository.get_by_id(job_id, tenant_a).status
    body = {"lease_id": str(lease_id)}

    foreign = _as(tenant_b).post(
        f"/workers/{worker.id}/jobs/{job_id}/{action}", json=body
    )
    missing_id = WorkerId.new()
    missing = _as(tenant_b).post(
        f"/workers/{missing_id}/jobs/{job_id}/{action}", json=body
    )

    assert foreign.status_code == 404
    assert foreign.status_code == missing.status_code
    assert foreign.text.replace(str(worker.id), "<id>") == (
        missing.text.replace(str(missing_id), "<id>")
    )

    stored_worker = _worker_repository.get_by_id(worker.id, worker.tenant_id)
    assert stored_worker is not None
    assert stored_worker.running_job is not None
    assert stored_worker.running_job.id == job_id
    lease = _lease_repository.get_by_worker_id(worker.id, worker.tenant_id)
    assert lease is not None
    assert lease.id == lease_id
    assert _job_repository.get_by_id(job_id, tenant_a).status == status_before
    assert not _job_repository.get_by_id(job_id, tenant_a).status.is_terminal
