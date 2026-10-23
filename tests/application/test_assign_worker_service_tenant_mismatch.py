"""ADR 0075, slice 1: a lease refused for a tenant mismatch strands no job.

AcquireLeaseService refuses a job whose tenant differs from its worker's.
The scheduler never pairs them, so this should not happen. If it does,
the job must go back to the scheduler like any other refused assignment,
and nothing may be recorded for an assignment that did not happen.
"""

from __future__ import annotations

import logging

import pytest

from app.application.services.acquire_lease_service import (
    AcquireLeaseService,
)
from app.application.services.assign_worker_service import (
    AssignWorkerService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.exceptions.no_available_node_error import (
    NoAvailableNodeError,
)
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)
from app.infrastructure.repositories.in_memory_lease_repository import (
    InMemoryLeaseRepository,
)
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node
from tests.support.workers import make_worker


def test_a_tenant_mismatch_is_reported_as_no_available_node(
    caplog: pytest.LogCaptureFixture,
) -> None:
    worker_tenant = TenantId.new()
    job_tenant = TenantId.new()

    node = make_node(tenant_id=worker_tenant)
    worker = make_worker(node=node)
    worker.ready()

    job = make_job(tenant_id=job_tenant)
    job.queue()
    job.assign_to(node.id)

    events = InMemoryEventRepository()
    leases = InMemoryLeaseRepository()
    recorder = RecordJobEventsService(event_repository=events)

    service = AssignWorkerService(
        worker_repository=InMemoryWorkerRepository([worker]),
        acquire_lease_service=AcquireLeaseService(
            lease_repository=leases,
            record_job_events_service=recorder,
        ),
        record_job_events_service=recorder,
    )

    with caplog.at_level(logging.ERROR), pytest.raises(
        NoAvailableNodeError
    ):
        service.execute(job)

    assert leases.get_by_job_id(job.id, job.tenant_id) is None
    assert worker.is_idle()
    assert worker.running_job is None
    assert events.list(job_tenant) == []
    assert events.list(worker_tenant) == []

    refusals = [
        record
        for record in caplog.records
        if record.levelno == logging.ERROR
    ]
    assert len(refusals) == 1
    assert str(job.id) in refusals[0].getMessage()
