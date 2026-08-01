from __future__ import annotations

import pytest

from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.application.services.release_lease_service import (
    ReleaseLeaseService,
)
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
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
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)


def _make_worker_with_running_job() -> tuple[Worker, Job]:
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = Worker(
        id=WorkerId.new(),
        node=node,
    )

    worker.ready()

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
    )

    job.queue()
    job.assign_to(node.id)

    worker.accept(job)
    worker.start()

    return worker, job


def test_execute_deletes_the_lease() -> None:
    """
    ReleaseLeaseService is responsible for exactly one
    thing: removing the lease record. It must not decide,
    or even touch, the worker's or job's status -- that
    decision belongs to whichever caller actually knows the
    job's outcome (WorkerExecutionLoop), and must happen
    before this service is invoked.
    """
    worker, job = _make_worker_with_running_job()

    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    worker_repository = InMemoryWorkerRepository([worker])

    service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
    )

    service.execute(worker.id)

    assert lease_repository.get_by_worker_id(worker.id) is None
    assert lease_repository.get_by_job_id(job.id) is None


def test_execute_does_not_change_worker_state() -> None:
    """
    Guards against ReleaseLeaseService silently regaining
    responsibility for worker/job transitions. Whatever
    state the worker was in before release, it must be in
    that exact same state afterward.
    """
    worker, job = _make_worker_with_running_job()

    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    worker_repository = InMemoryWorkerRepository([worker])

    service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
    )

    service.execute(worker.id)

    stored_worker = worker_repository.get_by_id(worker.id)

    assert stored_worker is not None
    assert stored_worker.status == worker.status
    assert stored_worker.running_job is job


def test_execute_raises_when_worker_has_no_active_lease() -> None:
    worker, _job = _make_worker_with_running_job()

    lease_repository = InMemoryLeaseRepository()
    worker_repository = InMemoryWorkerRepository([worker])

    service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
    )

    with pytest.raises(
        ValueError,
        match="does not own an active lease",
    ):
        service.execute(worker.id)


def test_execute_raises_when_worker_does_not_exist() -> None:
    worker, job = _make_worker_with_running_job()

    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    worker_repository = InMemoryWorkerRepository()

    service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
    )

    with pytest.raises(
        ValueError,
        match="Worker does not exist",
    ):
        service.execute(worker.id)
def test_execute_records_lease_released_event() -> None:
    """
    Releasing a lease must record a LeaseReleased event.
    This is an observation of what happened, not a decision
    about the job's outcome -- it doesn't violate the
    "must not touch worker/job status" rule the other tests
    in this file guard, since recording an event mutates
    neither.
    """
    worker, job = _make_worker_with_running_job()

    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    worker_repository = InMemoryWorkerRepository([worker])
    events = InMemoryEventRepository()

    record_job_events_service = RecordJobEventsService(
        event_repository=events,
    )

    service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
        record_job_events_service=record_job_events_service,
    )

    service.execute(worker.id)

    recorded = events.list()

    assert len(recorded) == 1
    assert recorded[0].event_type == "LeaseReleased"
    assert recorded[0].aggregate_id == str(job.id)
    assert recorded[0].aggregate_type == "Job"
