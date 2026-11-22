from datetime import timedelta

import pytest

from app.application.services.acquire_lease_service import (
    AcquireLeaseService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.lease import Lease
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)
from app.infrastructure.repositories.in_memory_lease_repository import (
    InMemoryLeaseRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node
from tests.support.workers import make_worker


def test_worker_can_acquire_job_lease() -> None:
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=4,
            memory_mib=4096,
            vram_mib=0,
        ),
    )

    worker = make_worker(
        id=WorkerId.new(),
        node=node,
    )

    job = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
    )

    repository = InMemoryLeaseRepository()

    service = AcquireLeaseService(
        repository,
    )

    lease = service.execute(
        worker,
        job,
    )

    assert lease.worker_id == worker.id
    assert lease.job_id == job.id
    assert repository.get_by_job_id(job.id, job.tenant_id) is not None
def test_acquire_lease_service_records_lease_acquired_event() -> None:
    """
    Acquiring a lease must record a LeaseAcquired event, the
    same way assignment already records WorkerAssigned.
    """
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=4,
            memory_mib=4096,
            vram_mib=0,
        ),
    )

    worker = make_worker(
        id=WorkerId.new(),
        node=node,
    )

    job = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
    )

    repository = InMemoryLeaseRepository()
    events = InMemoryEventRepository()

    record_job_events_service = RecordJobEventsService(
        event_repository=events,
    )

    service = AcquireLeaseService(
        repository,
        record_job_events_service=record_job_events_service,
    )

    service.execute(
        worker,
        job,
    )

    recorded = events.list(DEFAULT_TENANT_ID)

    assert len(recorded) == 1
    assert recorded[0].event_type == "LeaseAcquired"
    assert recorded[0].aggregate_id == str(job.id)
    assert recorded[0].aggregate_type == "Job"


def test_a_second_worker_cannot_take_a_job_that_already_has_a_lease() -> None:
    """
    A job holds at most one lease. A second worker asking for the
    same job is refused, the first lease stays the stored lease,
    and no second LeaseAcquired event is recorded.
    """
    first_worker = make_worker(node=make_node())
    second_worker = make_worker(node=make_node())
    job = make_job()

    leases = InMemoryLeaseRepository()
    events = InMemoryEventRepository()
    service = AcquireLeaseService(
        leases,
        record_job_events_service=RecordJobEventsService(
            event_repository=events,
        ),
    )

    first = service.execute(first_worker, job)

    with pytest.raises(ValueError, match="already has an active lease"):
        service.execute(second_worker, job)

    stored = leases.get_by_job_id(job.id, job.tenant_id)
    assert stored is not None
    assert stored.id == first.id
    assert stored.worker_id == first_worker.id

    recorded = events.list(job.tenant_id)
    assert [event.event_type for event in recorded] == ["LeaseAcquired"]


def test_an_expired_lease_still_blocks_a_second_worker() -> None:
    """
    Acquire never replaces a lease, even an expired one. Only
    reconciliation deletes an expired lease, through
    delete_if_expired. Until then the second worker is refused,
    the expired lease stays stored and no event is recorded.
    """
    first_worker = make_worker(node=make_node())
    second_worker = make_worker(node=make_node())
    job = make_job()

    expired = Lease.create(
        worker_id=first_worker.id,
        job_id=job.id,
        tenant_id=job.tenant_id,
        duration=timedelta(seconds=-1),
    )
    leases = InMemoryLeaseRepository()
    leases.save(expired)
    events = InMemoryEventRepository()
    service = AcquireLeaseService(
        leases,
        record_job_events_service=RecordJobEventsService(
            event_repository=events,
        ),
    )

    assert expired.is_expired()

    with pytest.raises(ValueError, match="already has an active lease"):
        service.execute(second_worker, job)

    stored = leases.get_by_job_id(job.id, job.tenant_id)
    assert stored is not None
    assert stored.id == expired.id
    assert stored.worker_id == first_worker.id
    assert events.list(job.tenant_id) == []
