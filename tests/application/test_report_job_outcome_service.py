from __future__ import annotations

import pytest

from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.application.services.release_lease_service import (
    ReleaseLeaseService,
)
from app.application.services.report_job_outcome_service import (
    ReportJobOutcomeService,
)
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.exceptions.worker_job_mismatch_error import (
    WorkerJobMismatchError,
)
from app.domain.exceptions.worker_not_found_error import (
    WorkerNotFoundError,
)
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
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)


def _make_running_worker_and_job() -> tuple[Worker, Job, Node]:
    """
    Same fixture shape as test_worker_execution_loop.py's
    _make_worker_and_job, but additionally calls worker.start()
    to reach RUNNING -- required for complete(), since
    Job._ALLOWED_TRANSITIONS only permits COMPLETED from
    RUNNING, not SCHEDULED.
    """
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
    node.allocate(job.resources)

    worker.accept(job)
    worker.start()

    return worker, job, node


def _build_service(
    worker: Worker,
    job: Job,
    node: Node,
    record_job_events_service: RecordJobEventsService | None = None,
) -> tuple[
    ReportJobOutcomeService,
    InMemoryWorkerRepository,
    InMemoryJobRepository,
    InMemoryNodeRepository,
    InMemoryLeaseRepository,
]:
    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])
    node_repository = InMemoryNodeRepository([node])

    release_lease_service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
    )

    service = ReportJobOutcomeService(
        worker_repository=worker_repository,
        job_repository=job_repository,
        node_repository=node_repository,
        release_lease_service=release_lease_service,
        record_job_events_service=record_job_events_service,
    )

    return (
        service,
        worker_repository,
        job_repository,
        node_repository,
        lease_repository,
    )


def test_complete_marks_job_completed_releases_lease_and_node() -> None:
    worker, job, node = _make_running_worker_and_job()

    service, worker_repository, job_repository, node_repository, lease_repository = (
        _build_service(worker, job, node)
    )

    service.complete(
        worker.id,
        job.id,
        exit_code=0,
    )

    saved_worker = worker_repository.get_by_id(worker.id)
    saved_job = job_repository.get_by_id(job.id)
    saved_node = node_repository.get_by_id(node.id)

    assert saved_worker is not None
    assert saved_worker.is_idle()
    assert saved_worker.running_job is None

    assert saved_job is not None
    assert saved_job.is_completed()
    assert saved_job.exit_code == 0

    assert lease_repository.get_by_worker_id(worker.id) is None

    assert saved_node is not None
    assert saved_node.available == saved_node.capacity


def test_fail_marks_job_failed_releases_lease_and_node() -> None:
    worker, job, node = _make_running_worker_and_job()

    service, worker_repository, job_repository, node_repository, lease_repository = (
        _build_service(worker, job, node)
    )

    service.fail(
        worker.id,
        job.id,
        exit_code=1,
    )

    saved_worker = worker_repository.get_by_id(worker.id)
    saved_job = job_repository.get_by_id(job.id)
    saved_node = node_repository.get_by_id(node.id)

    assert saved_worker is not None
    assert saved_worker.is_idle()

    assert saved_job is not None
    assert saved_job.is_failed()
    assert saved_job.exit_code == 1

    assert lease_repository.get_by_worker_id(worker.id) is None

    assert saved_node is not None
    assert saved_node.available == saved_node.capacity


def test_complete_records_job_completed_event() -> None:
    worker, job, node = _make_running_worker_and_job()

    events = InMemoryEventRepository()
    record_job_events_service = RecordJobEventsService(
        event_repository=events,
    )

    service, *_ = _build_service(
        worker, job, node, record_job_events_service,
    )

    service.complete(
        worker.id,
        job.id,
    )

    recorded = events.list()

    assert len(recorded) == 1
    assert recorded[0].event_type == "JobCompleted"
    assert recorded[0].aggregate_id == str(job.id)
    assert recorded[0].aggregate_type == "Job"


def test_fail_records_job_failed_event() -> None:
    worker, job, node = _make_running_worker_and_job()

    events = InMemoryEventRepository()
    record_job_events_service = RecordJobEventsService(
        event_repository=events,
    )

    service, *_ = _build_service(
        worker, job, node, record_job_events_service,
    )

    service.fail(
        worker.id,
        job.id,
    )

    recorded = events.list()

    assert len(recorded) == 1
    assert recorded[0].event_type == "JobFailed"
    assert recorded[0].aggregate_id == str(job.id)
    assert recorded[0].aggregate_type == "Job"


def test_complete_raises_worker_not_found_error() -> None:
    worker, job, node = _make_running_worker_and_job()

    service, *_ = _build_service(worker, job, node)

    with pytest.raises(WorkerNotFoundError):
        service.complete(
            WorkerId.new(),
            job.id,
        )


def test_complete_raises_worker_job_mismatch_when_worker_holds_different_job() -> None:
    worker, job, node = _make_running_worker_and_job()

    service, *_ = _build_service(worker, job, node)

    with pytest.raises(WorkerJobMismatchError):
        service.complete(
            worker.id,
            JobId.new(),
        )


def test_complete_raises_worker_job_mismatch_when_worker_holds_no_job() -> None:
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

    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository()
    node_repository = InMemoryNodeRepository([node])
    lease_repository = InMemoryLeaseRepository()

    service = ReportJobOutcomeService(
        worker_repository=worker_repository,
        job_repository=job_repository,
        node_repository=node_repository,
        release_lease_service=ReleaseLeaseService(
            lease_repository=lease_repository,
            worker_repository=worker_repository,
        ),
    )

    with pytest.raises(WorkerJobMismatchError):
        service.complete(
            worker.id,
            JobId.new(),
        )


def test_fail_raises_worker_not_found_error() -> None:
    worker, job, node = _make_running_worker_and_job()

    service, *_ = _build_service(worker, job, node)

    with pytest.raises(WorkerNotFoundError):
        service.fail(
            WorkerId.new(),
            job.id,
        )
