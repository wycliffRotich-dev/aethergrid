from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.domain.entities.tenant import Tenant
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId
from app.presentation.api import app
from app.presentation.auth import require_api_key
from app.presentation.dependencies import (
    _job_repository,
    _tenant_repository,
    get_node_repository,
)
from tests.support.api_keys import make_api_key
from tests.support.jobs import make_job
from tests.support.nodes import make_node


def _new_tenant() -> TenantId:
    tenant = Tenant.create(f"t-{uuid.uuid4().hex[:8]}")
    _tenant_repository.save(tenant)
    return tenant.id


def _as(tenant_id: TenantId) -> TestClient:
    # A plain client, never the lifespan context manager, so the
    # background cluster tick cannot complete or schedule a job
    # while a test asserts that it is unchanged.
    caller, _ = make_api_key(label="caller", tenant_id=tenant_id)
    app.dependency_overrides[require_api_key] = lambda: caller
    return TestClient(app)


def _masked(response, job_id) -> str:
    return response.text.replace(str(job_id), "<id>")


def _snapshot(job):
    return (
        job.status,
        job.retry_count,
        job.assigned_node_id,
        job.cancellation_requested_at,
        job.completed_at,
        job.exit_code,
    )


def _queued_job(tenant_id: TenantId):
    job = make_job(tenant_id=tenant_id)
    job.queue()
    _job_repository.save(job)
    return job


def _failed_job(tenant_id: TenantId):
    # The job is assigned to a real node in its own tenant, because
    # jobs.assigned_node_id is a foreign key to nodes.
    node = make_node(tenant_id=tenant_id)
    get_node_repository().save(node)
    job = make_job(tenant_id=tenant_id, max_retries=3)
    job.queue()
    job.assign_to(node.id)
    job.start()
    job.fail(exit_code=1)
    _job_repository.save(job)
    return job


@pytest.fixture
def tenant_a() -> TenantId:
    return _new_tenant()


@pytest.fixture
def tenant_b() -> TenantId:
    return _new_tenant()


@pytest.mark.parametrize(
    ("method", "template", "build", "owner_status"),
    [
        ("GET", "/jobs/{id}", _queued_job, 200),
        ("POST", "/jobs/{id}/cancel", _queued_job, 200),
        ("POST", "/jobs/{id}/retry", _failed_job, 200),
    ],
)
def test_another_tenants_job_answers_like_a_missing_one(
    tenant_a, tenant_b, method, template, build, owner_status
) -> None:
    job = build(tenant_a)
    before = _snapshot(_job_repository.get_by_id(job.id, tenant_a))
    missing_id = JobId.new()

    client = _as(tenant_b)
    foreign = client.request(method, template.format(id=job.id))
    missing = client.request(method, template.format(id=missing_id))

    assert foreign.status_code == 404
    assert foreign.status_code == missing.status_code
    assert _masked(foreign, job.id) == _masked(missing, missing_id)

    stored = _job_repository.get_by_id(job.id, tenant_a)
    assert stored is not None
    assert _snapshot(stored) == before

    owner = _as(tenant_a).request(method, template.format(id=job.id))
    assert owner.status_code == owner_status


def test_the_history_of_another_tenants_job_is_empty(
    tenant_a, tenant_b
) -> None:
    job = _queued_job(tenant_a)

    foreign = _as(tenant_b).get(f"/jobs/{job.id}/history")
    missing = _as(tenant_b).get(f"/jobs/{JobId.new()}/history")

    assert foreign.status_code == missing.status_code == 200
    assert foreign.json() == missing.json() == {"events": []}


def test_list_jobs_returns_only_the_callers_tenant(
    tenant_a, tenant_b
) -> None:
    job_a = _queued_job(tenant_a)
    job_b = _queued_job(tenant_b)

    ids_a = {j["id"] for j in _as(tenant_a).get("/jobs").json()["jobs"]}
    ids_b = {j["id"] for j in _as(tenant_b).get("/jobs").json()["jobs"]}

    assert ids_a == {str(job_a.id)}
    assert ids_b == {str(job_b.id)}


def test_list_queued_jobs_returns_only_the_callers_tenant(
    tenant_a, tenant_b
) -> None:
    job_a = _queued_job(tenant_a)
    job_b = _queued_job(tenant_b)

    ids_a = {
        j["id"] for j in _as(tenant_a).get("/jobs/queued").json()["jobs"]
    }
    ids_b = {
        j["id"] for j in _as(tenant_b).get("/jobs/queued").json()["jobs"]
    }

    assert ids_a == {str(job_a.id)}
    assert ids_b == {str(job_b.id)}


def test_a_created_job_belongs_to_the_callers_tenant(tenant_a) -> None:
    response = _as(tenant_a).post(
        "/jobs",
        json={"cpu_cores": 1, "memory_mib": 512, "vram_mib": 0},
    )

    assert response.status_code == 201
    job_id = JobId(value=uuid.UUID(response.json()["id"]))
    stored = _job_repository.get_by_id(job_id, tenant_a)
    assert stored is not None
    assert stored.tenant_id == tenant_a


def test_a_tenant_in_the_request_body_is_ignored(tenant_a, tenant_b) -> None:
    response = _as(tenant_a).post(
        "/jobs",
        json={
            "cpu_cores": 1,
            "memory_mib": 512,
            "vram_mib": 0,
            "tenant_id": str(tenant_b),
        },
    )

    assert response.status_code == 201
    job_id = JobId(value=uuid.UUID(response.json()["id"]))
    assert _job_repository.get_by_id(job_id, tenant_a) is not None
    assert _job_repository.get_by_id(job_id, tenant_b) is None
