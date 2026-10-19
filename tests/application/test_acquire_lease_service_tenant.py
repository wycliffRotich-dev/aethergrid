from __future__ import annotations

import pytest

from app.application.services.acquire_lease_service import (
    AcquireLeaseService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.entities.worker import Worker
from app.domain.exceptions.lease_tenant_mismatch_error import (
    LeaseTenantMismatchError,
)
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)
from app.infrastructure.repositories.in_memory_lease_repository import (
    InMemoryLeaseRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node
from tests.support.workers import make_worker


def _worker_in(tenant_id: TenantId) -> Worker:
    return make_worker(node=make_node(tenant_id=tenant_id))


def test_the_lease_takes_the_tenant_of_its_worker() -> None:
    tenant = TenantId.new()
    worker = _worker_in(tenant)
    job = make_job(tenant_id=tenant)
    service = AcquireLeaseService(InMemoryLeaseRepository())

    lease = service.execute(worker, job)

    assert lease.tenant_id == tenant
    assert lease.tenant_id != DEFAULT_TENANT_ID


def test_a_job_in_another_tenant_gets_no_lease_and_records_nothing() -> None:
    tenant_a = TenantId.new()
    tenant_b = TenantId.new()
    worker = _worker_in(tenant_a)
    job = make_job(tenant_id=tenant_b)
    leases = InMemoryLeaseRepository()
    events = InMemoryEventRepository()
    service = AcquireLeaseService(
        leases,
        RecordJobEventsService(event_repository=events),
    )

    with pytest.raises(LeaseTenantMismatchError):
        service.execute(worker, job)

    assert leases.get_by_job_id(job.id) is None
    assert events.list(tenant_a) == []
    assert events.list(tenant_b) == []
