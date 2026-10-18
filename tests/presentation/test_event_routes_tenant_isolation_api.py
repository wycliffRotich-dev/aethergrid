from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.tenant import Tenant
from app.domain.value_objects.tenant_id import TenantId
from app.presentation.api import app
from app.presentation.auth import require_api_key
from app.presentation.dependencies import (
    _event_repository,
    _job_repository,
    _tenant_repository,
)
from tests.support.api_keys import make_api_key
from tests.support.jobs import make_job


def _new_tenant() -> TenantId:
    tenant = Tenant.create(f"t-{uuid.uuid4().hex[:8]}")
    _tenant_repository.save(tenant)
    return tenant.id


def _as(tenant_id: TenantId) -> TestClient:
    # A plain client, never the lifespan context manager, so the
    # background cluster tick cannot record events while a test
    # asserts what the feed returns.
    caller, _ = make_api_key(label="caller", tenant_id=tenant_id)
    app.dependency_overrides[require_api_key] = lambda: caller
    return TestClient(app)


def _job_with_events(tenant_id: TenantId, event_types: list[str]):
    job = make_job(tenant_id=tenant_id)
    job.queue()
    _job_repository.save(job)
    recorder = RecordJobEventsService(event_repository=_event_repository)
    for event_type in event_types:
        recorder.record_for_job(job, event_type=event_type)
    return job


@pytest.fixture
def tenant_a() -> TenantId:
    return _new_tenant()


@pytest.fixture
def tenant_b() -> TenantId:
    return _new_tenant()


def test_the_feed_holds_only_the_callers_own_events(
    tenant_a: TenantId, tenant_b: TenantId
) -> None:
    job_a = _job_with_events(tenant_a, ["JobCreated", "JobScheduled"])
    job_b = _job_with_events(tenant_b, ["JobCreated"])

    own = _as(tenant_a).get("/events")
    foreign = _as(tenant_b).get("/events")

    assert own.status_code == 200
    own_ids = {e["aggregate_id"] for e in own.json()["events"]}
    assert str(job_a.id) in own_ids
    assert str(job_b.id) not in own_ids

    assert foreign.status_code == 200
    foreign_events = foreign.json()["events"]
    assert {e["aggregate_id"] for e in foreign_events} == {str(job_b.id)}
    assert len(foreign_events) == 1
    assert str(job_a.id) not in foreign.text


def test_a_tenant_with_no_events_gets_an_empty_feed(
    tenant_a: TenantId, tenant_b: TenantId
) -> None:
    job_a = _job_with_events(tenant_a, ["JobCreated"])

    response = _as(tenant_b).get("/events")

    assert response.status_code == 200
    assert response.json() == {"events": []}
    assert str(job_a.id) not in response.text
