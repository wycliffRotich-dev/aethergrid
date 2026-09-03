from __future__ import annotations

from datetime import timedelta

from app.application.reconciliation.recover_expired_lease_service import (
    RecoverExpiredLeaseService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
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
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from app.infrastructure.repositories.in_memory_lease_repository import (
    InMemoryLeaseRepository,
)
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)


def _make_node() -> Node:
    return Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )


def _make_expired_lease(worker: Worker, job: Job) -> Lease:
    return Lease.create(
        worker_id=worker.id,
        job_id=job.id,
        duration=timedelta(seconds=-1),
    )


def test_recover_expired_lease_requeues_job_with_retries_remaining() -> None:
    """
    A job whose lease expired mid-execution, with retry
    budget remaining, is reclaimed back to QUEUED rather
    than left stuck or incorrectly failed outright.
    """
    node = _make_node()

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
        max_retries=1,
    )

    job.queue()
    job.assign_to(node.id)

    worker.accept(job)
    worker.start()

    lease = _make_expired_lease(worker, job)

    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])
    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    service = RecoverExpiredLeaseService(
        worker_repository=worker_repository,
        job_repository=job_repository,
        lease_repository=lease_repository,
    )

    service.execute()

    recovered_worker = worker_repository.get_by_id(worker.id)
    recovered_job = job_repository.get_by_id(job.id)

    assert recovered_worker is not None
    assert recovered_worker.is_idle()

    assert recovered_job is not None
    assert recovered_job.is_queued()
    assert recovered_job.retry_count == 1

    assert (
        lease_repository.get_by_worker_id(worker.id) is None
    )


def test_recover_expired_lease_fails_job_once_retries_exhausted() -> None:
    """
    A job with no retry budget remaining is failed outright
    when its lease expires, rather than being requeued
    forever onto a fleet that may keep abandoning it.
    """
    node = _make_node()

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
        max_retries=0,
    )

    job.queue()
    job.assign_to(node.id)

    worker.accept(job)
    worker.start()

    lease = _make_expired_lease(worker, job)

    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])
    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    service = RecoverExpiredLeaseService(
        worker_repository=worker_repository,
        job_repository=job_repository,
        lease_repository=lease_repository,
    )

    service.execute()

    recovered_worker = worker_repository.get_by_id(worker.id)
    recovered_job = job_repository.get_by_id(job.id)

    assert recovered_worker is not None
    assert recovered_worker.is_idle()

    assert recovered_job is not None
    assert recovered_job.is_failed()

    assert (
        lease_repository.get_by_worker_id(worker.id) is None
    )
def test_recover_expired_lease_records_job_reclaimed_event() -> None:
    """
    Reclaiming a job whose lease expired must record a
    JobReclaimed event.
    """
    node = _make_node()

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
        max_retries=1,
    )

    job.queue()
    job.assign_to(node.id)

    worker.accept(job)
    worker.start()

    lease = _make_expired_lease(worker, job)

    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])
    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    events = InMemoryEventRepository()
    record_job_events_service = RecordJobEventsService(
        event_repository=events,
    )

    service = RecoverExpiredLeaseService(
        worker_repository=worker_repository,
        job_repository=job_repository,
        lease_repository=lease_repository,
        record_job_events_service=record_job_events_service,
    )

    service.execute()

    recorded = events.list()

    assert len(recorded) == 1
    assert recorded[0].event_type == "JobReclaimed"
    assert recorded[0].aggregate_id == str(job.id)
    assert recorded[0].aggregate_type == "Job"


def test_recover_expired_lease_finalizes_cancelling_job_as_cancelled() -> None:
    """
    A job that was CANCELLING when its worker died is
    finalized as CANCELLED, not requeued, since cancellation
    was already requested before the worker died (ADR 0031).
    No retry attempt is consumed.
    """
    node = _make_node()

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
        max_retries=1,
    )

    job.queue()
    job.assign_to(node.id)

    worker.accept(job)
    worker.start()
    job.request_cancellation()

    lease = _make_expired_lease(worker, job)

    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])
    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    service = RecoverExpiredLeaseService(
        worker_repository=worker_repository,
        job_repository=job_repository,
        lease_repository=lease_repository,
    )

    service.execute()

    recovered_worker = worker_repository.get_by_id(worker.id)
    recovered_job = job_repository.get_by_id(job.id)

    assert recovered_worker is not None
    assert recovered_worker.is_idle()

    assert recovered_job is not None
    assert recovered_job.is_cancelled()
    assert recovered_job.retry_count == 0

    assert (
        lease_repository.get_by_worker_id(worker.id) is None
    )


def test_recover_expired_lease_records_job_cancelled_event_for_cancelling_job() -> None:
    """
    Reclaiming a job that was CANCELLING when its lease
    expired must record JobCancelled, not the generic
    JobReclaimed used for the SCHEDULED/RUNNING retry path,
    since the event history should describe what actually
    happened to the job (ADR 0031).
    """
    node = _make_node()

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
        max_retries=1,
    )

    job.queue()
    job.assign_to(node.id)

    worker.accept(job)
    worker.start()
    job.request_cancellation()

    lease = _make_expired_lease(worker, job)

    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])
    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    events = InMemoryEventRepository()
    record_job_events_service = RecordJobEventsService(
        event_repository=events,
    )

    service = RecoverExpiredLeaseService(
        worker_repository=worker_repository,
        job_repository=job_repository,
        lease_repository=lease_repository,
        record_job_events_service=record_job_events_service,
    )

    service.execute()

    recorded = events.list()

    assert len(recorded) == 1
    assert recorded[0].event_type == "JobCancelled"
    assert recorded[0].aggregate_id == str(job.id)
    assert recorded[0].aggregate_type == "Job"
