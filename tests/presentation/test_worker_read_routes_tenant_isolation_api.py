from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.domain.entities.tenant import Tenant
from app.domain.entities.worker import Worker
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId
from app.presentation.api import app
from app.presentation.auth import require_api_key
from app.presentation.dependencies import (
    _job_repository,
    _tenant_repository,
    _worker_repository,
    get_node_repository,
)
from tests.support.api_keys import make_api_key
from tests.support.jobs import make_job
from tests.support.nodes import make_node
from tests.support.workers import make_worker

SECRET_COMMAND = "tenant-a-secret"


def _new_tenant() -> TenantId:
    tenant = Tenant.create(f"t-{uuid.uuid4().hex[:8]}")
    _tenant_repository.save(tenant)
    return tenant.id


def _as(tenant_id: TenantId) -> TestClient:
    caller, _ = make_api_key(label="caller", tenant_id=tenant_id)
    app.dependency_overrides[require_api_key] = lambda: caller
    return TestClient(app)


def _worker_running_a_job(tenant_id: TenantId) -> Worker:
    node = make_node(tenant_id=tenant_id)
    get_node_repository().save(node)
    job = make_job(
        tenant_id=tenant_id,
        assigned_node_id=node.id,
        command=["echo", SECRET_COMMAND],
    )
    _job_repository.save(job)
    worker = make_worker(node=node)
    worker.ready()
    worker.accept(job)
    _worker_repository.save(worker)
    return worker


@pytest.fixture
def tenant_a() -> TenantId:
    return _new_tenant()


@pytest.fixture
def tenant_b() -> TenantId:
    return _new_tenant()


def test_another_tenants_worker_answers_like_a_missing_one(
    tenant_a: TenantId, tenant_b: TenantId
) -> None:
    worker = _worker_running_a_job(tenant_a)

    foreign = _as(tenant_b).get(f"/workers/{worker.id}")
    missing = _as(tenant_b).get(f"/workers/{WorkerId.new()}")

    assert foreign.status_code == 404
    assert foreign.status_code == missing.status_code
    assert foreign.json() == missing.json()

    owner = _as(tenant_a).get(f"/workers/{worker.id}")
    assert owner.status_code == 200


def test_another_tenants_job_command_is_never_exposed(
    tenant_a: TenantId, tenant_b: TenantId
) -> None:
    worker = _worker_running_a_job(tenant_a)

    foreign = _as(tenant_b).get(f"/workers/{worker.id}")

    assert SECRET_COMMAND not in foreign.text


def test_list_workers_returns_only_the_callers_tenant(
    tenant_a: TenantId, tenant_b: TenantId
) -> None:
    worker = _worker_running_a_job(tenant_a)

    foreign = _as(tenant_b).get("/workers")
    owner = _as(tenant_a).get("/workers")

    assert foreign.status_code == 200
    assert foreign.json()["workers"] == []
    assert [w["id"] for w in owner.json()["workers"]] == [str(worker.id)]


def test_another_tenants_worker_cannot_renew_a_lease(
    tenant_a: TenantId, tenant_b: TenantId
) -> None:
    worker = _worker_running_a_job(tenant_a)
    body = {"lease_id": str(uuid.uuid4())}

    foreign = _as(tenant_b).post(
        f"/workers/{worker.id}/lease/renew", json=body
    )
    missing = _as(tenant_b).post(
        f"/workers/{WorkerId.new()}/lease/renew", json=body
    )

    assert foreign.status_code == 404
    assert foreign.status_code == missing.status_code
    assert foreign.json() == missing.json()
