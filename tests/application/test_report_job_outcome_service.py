from __future__ import annotations

from uuid import uuid4

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
from app.domain.entities.tenant import DEFAULT_TENANT_ID
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
from app.domain.value_objects.tenant_id import TenantId
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
from tests.support.jobs import make_job
from tests.support.nodes import make_node
from tests.support.workers import make_worker


def _make_running_worker_and_job() -> tuple[Worker, Job, Node]:
    """
    Same fixture shape as test_worker_execution_loop.py's
    _make_worker_and_job, but additionally calls worker.start()
    to reach RUNNING -- required for complete(), since
    Job._ALLOWED_TRANSITIONS only permits COMPLETED from
    RUNNING, not SCHEDULED.
    """
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = make_worker(
        id=WorkerId.new(),
        node=node,
    )
    worker.ready()

    job = make_job(
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
    Lease,
]:
    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
        tenant_id=worker.tenant_id,
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
        lease_repository=lease_repository,
        release_lease_service=release_lease_service,
        record_job_events_service=record_job_events_service,
    )

    return (
        service,
        worker_repository,
        job_repository,
        node_repository,
        lease_repository,
        lease,
    )


def test_complete_marks_job_completed_releases_lease_and_node() -> None:
    worker, job, node = _make_running_worker_and_job()

    (
        service,
        worker_repository,
        job_repository,
        node_repository,
        lease_repository,
        lease,
    ) = _build_service(worker, job, node)

    service.complete(
        worker.id,
        job.id,
        tenant_id=DEFAULT_TENANT_ID,
        lease_id=lease.id,
        exit_code=0,
    )

    saved_worker = worker_repository.get_by_id(worker.id, worker.tenant_id)
    saved_job = job_repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    saved_node = node_repository.get_by_id(node.id, DEFAULT_TENANT_ID)

    assert saved_worker is not None
    assert saved_worker.is_idle()
    assert saved_worker.running_job is None

    assert saved_job is not None
    assert saved_job.is_completed()
    assert saved_job.exit_code == 0

    assert lease_repository.get_by_worker_id(worker.id, worker.tenant_id) is None

    assert saved_node is not None
    assert saved_node.available == saved_node.capacity


def test_fail_marks_job_failed_releases_lease_and_node() -> None:
    worker, job, node = _make_running_worker_and_job()

    (
        service,
        worker_repository,
        job_repository,
        node_repository,
        lease_repository,
        lease,
    ) = _build_service(worker, job, node)

    service.fail(
        worker.id,
        job.id,
        tenant_id=DEFAULT_TENANT_ID,
        lease_id=lease.id,
        exit_code=1,
    )

    saved_worker = worker_repository.get_by_id(worker.id, worker.tenant_id)
    saved_job = job_repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    saved_node = node_repository.get_by_id(node.id, DEFAULT_TENANT_ID)

    assert saved_worker is not None
    assert saved_worker.is_idle()

    assert saved_job is not None
    assert saved_job.is_failed()
    assert saved_job.exit_code == 1

    assert lease_repository.get_by_worker_id(worker.id, worker.tenant_id) is None

    assert saved_node is not None
    assert saved_node.available == saved_node.capacity


def test_complete_records_job_completed_event() -> None:
    worker, job, node = _make_running_worker_and_job()

    events = InMemoryEventRepository()
    record_job_events_service = RecordJobEventsService(
        event_repository=events,
    )

    service, *_, lease = _build_service(
        worker, job, node, record_job_events_service,
    )

    service.complete(
        worker.id,
        job.id,
        tenant_id=DEFAULT_TENANT_ID,
        lease_id=lease.id,
    )

    recorded = events.list(DEFAULT_TENANT_ID)

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

    service, *_, lease = _build_service(
        worker, job, node, record_job_events_service,
    )

    service.fail(
        worker.id,
        job.id,
        tenant_id=DEFAULT_TENANT_ID,
        lease_id=lease.id,
    )

    recorded = events.list(DEFAULT_TENANT_ID)

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
            tenant_id=DEFAULT_TENANT_ID,
            lease_id=uuid4(),
        )


def test_complete_raises_worker_job_mismatch_when_worker_holds_different_job() -> None:
    worker, job, node = _make_running_worker_and_job()

    service, *_ = _build_service(worker, job, node)

    with pytest.raises(WorkerJobMismatchError):
        service.complete(
            worker.id,
            JobId.new(),
            tenant_id=DEFAULT_TENANT_ID,
            lease_id=uuid4(),
        )


def test_complete_raises_worker_job_mismatch_when_worker_holds_no_job() -> None:
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )
    worker = make_worker(
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
        lease_repository=lease_repository,
        release_lease_service=ReleaseLeaseService(
            lease_repository=lease_repository,
            worker_repository=worker_repository,
        ),
    )

    with pytest.raises(WorkerJobMismatchError):
        service.complete(
            worker.id,
            JobId.new(),
            tenant_id=DEFAULT_TENANT_ID,
            lease_id=uuid4(),
        )


def test_fail_raises_worker_not_found_error() -> None:
    worker, job, node = _make_running_worker_and_job()

    service, *_ = _build_service(worker, job, node)

    with pytest.raises(WorkerNotFoundError):
        service.fail(
            WorkerId.new(),
            job.id,
            tenant_id=DEFAULT_TENANT_ID,
            lease_id=uuid4(),
        )


def test_cancel_marks_job_cancelled_releases_lease_and_node() -> None:
    worker, job, node = _make_running_worker_and_job()
    job.request_cancellation()

    (
        service,
        worker_repository,
        job_repository,
        node_repository,
        lease_repository,
        lease,
    ) = _build_service(worker, job, node)

    service.cancel(
        worker.id,
        job.id,
        tenant_id=DEFAULT_TENANT_ID,
        lease_id=lease.id,
        exit_code=-15,
    )

    saved_worker = worker_repository.get_by_id(worker.id, worker.tenant_id)
    saved_job = job_repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    saved_node = node_repository.get_by_id(node.id, DEFAULT_TENANT_ID)

    assert saved_worker is not None
    assert saved_worker.is_idle()
    assert saved_worker.running_job is None

    assert saved_job is not None
    assert saved_job.is_cancelled()
    assert saved_job.exit_code == -15

    assert lease_repository.get_by_worker_id(worker.id, worker.tenant_id) is None

    assert saved_node is not None
    assert saved_node.available == saved_node.capacity


def test_cancel_records_job_cancelled_event() -> None:
    worker, job, node = _make_running_worker_and_job()
    job.request_cancellation()

    events = InMemoryEventRepository()
    record_job_events_service = RecordJobEventsService(
        event_repository=events,
    )

    service, *_, lease = _build_service(
        worker, job, node, record_job_events_service,
    )

    service.cancel(
        worker.id,
        job.id,
        tenant_id=DEFAULT_TENANT_ID,
        lease_id=lease.id,
    )

    recorded = events.list(DEFAULT_TENANT_ID)

    assert len(recorded) == 1
    assert recorded[0].event_type == "JobCancelled"
    assert recorded[0].aggregate_id == str(job.id)
    assert recorded[0].aggregate_type == "Job"


def test_cancel_raises_worker_not_found_error() -> None:
    worker, job, node = _make_running_worker_and_job()
    job.request_cancellation()

    service, *_ = _build_service(worker, job, node)

    with pytest.raises(WorkerNotFoundError):
        service.cancel(
            WorkerId.new(),
            job.id,
            tenant_id=DEFAULT_TENANT_ID,
            lease_id=uuid4(),
        )


def test_cancel_raises_worker_job_mismatch_when_worker_holds_different_job() -> None:
    worker, job, node = _make_running_worker_and_job()
    job.request_cancellation()

    service, *_ = _build_service(worker, job, node)

    with pytest.raises(WorkerJobMismatchError):
        service.cancel(
            worker.id,
            JobId.new(),
            tenant_id=DEFAULT_TENANT_ID,
            lease_id=uuid4(),
        )


def _make_running_worker_and_job_in(
    tenant: TenantId,
) -> tuple[Worker, Job, Node]:
    node = make_node(
        id=NodeId.new(),
        tenant_id=tenant,
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = make_worker(
        id=WorkerId.new(),
        node=node,
    )
    worker.ready()

    job = make_job(
        id=JobId.new(),
        tenant_id=tenant,
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


def test_complete_in_a_non_default_tenant_releases_node_and_records_event() -> None:
    """
    Worker, job and node share one tenant that is not the default. The
    node is found by the scoped read, its resources are released, and
    the event lands in that tenant (ADR 0074 decision 2, ADR 0075).
    """
    tenant = TenantId.new()
    assert tenant != DEFAULT_TENANT_ID
    worker, job, node = _make_running_worker_and_job_in(tenant)

    events = InMemoryEventRepository()
    (
        service,
        _worker_repository,
        job_repository,
        node_repository,
        lease_repository,
        lease,
    ) = _build_service(
        worker,
        job,
        node,
        record_job_events_service=RecordJobEventsService(
            event_repository=events,
        ),
    )

    service.complete(
        worker.id,
        job.id,
        tenant_id=tenant,
        lease_id=lease.id,
        exit_code=0,
    )

    saved_node = node_repository.get_by_id(node.id, tenant)
    saved_job = job_repository.get_by_id(job.id, tenant)

    assert saved_node is not None
    assert saved_node.available == saved_node.capacity
    assert saved_job is not None
    assert saved_job.is_completed()
    assert lease_repository.get_by_worker_id(worker.id, tenant) is None

    recorded = events.list(tenant)
    assert [e.event_type for e in recorded] == ["JobCompleted"]
    assert recorded[0].tenant_id == tenant
    assert events.list(DEFAULT_TENANT_ID) == []


def test_complete_never_releases_a_node_of_another_tenant() -> None:
    """
    The database forbids a job assigned to a node of another tenant
    (ADR 0069). If that state ever existed, the scoped node read must
    not find the node: its allocation stays untouched. The outcome is
    still recorded, since the lease is released and the worker saved
    before the node is read.
    """
    tenant = TenantId.new()
    other_tenant = TenantId.new()
    worker, job, node = _make_running_worker_and_job_in(tenant)

    foreign_node = make_node(
        id=node.id,
        tenant_id=other_tenant,
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )
    foreign_node.allocate(job.resources)

    (
        service,
        worker_repository,
        job_repository,
        node_repository,
        lease_repository,
        lease,
    ) = _build_service(worker, job, foreign_node)

    service.complete(
        worker.id,
        job.id,
        tenant_id=tenant,
        lease_id=lease.id,
        exit_code=0,
    )

    assert node_repository.get_by_id(node.id, tenant) is None
    assert foreign_node.available.cpu_cores == 7
    assert foreign_node.available.memory_mib == 16384 - 512

    saved_job = job_repository.get_by_id(job.id, tenant)
    saved_worker = worker_repository.get_by_id(worker.id, tenant)
    assert saved_job is not None
    assert saved_job.is_completed()
    assert saved_worker is not None
    assert saved_worker.is_idle()
    assert lease_repository.get_by_worker_id(worker.id, tenant) is None


_REPORT_LOGGER = "app.application.services.report_job_outcome_service"


def test_complete_logs_an_error_when_the_assigned_node_is_not_found(
    caplog,
) -> None:
    """
    A job with an assigned node whose node is not found in its tenant
    cannot occur on Postgres, but nothing stops it on the in-memory and
    sqlite backends. The release is skipped, so it must be logged at
    error level, as ADR 0075 decision 14 does for a tenant mismatch.
    """
    import logging

    tenant = TenantId.new()
    other_tenant = TenantId.new()
    worker, job, node = _make_running_worker_and_job_in(tenant)

    foreign_node = make_node(
        id=node.id,
        tenant_id=other_tenant,
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )
    foreign_node.allocate(job.resources)

    (
        service,
        _worker_repository,
        _job_repository,
        _node_repository,
        _lease_repository,
        lease,
    ) = _build_service(worker, job, foreign_node)

    with caplog.at_level(logging.ERROR, logger=_REPORT_LOGGER):
        service.complete(
            worker.id,
            job.id,
            tenant_id=tenant,
            lease_id=lease.id,
            exit_code=0,
        )

    errors = [
        r
        for r in caplog.records
        if r.name == _REPORT_LOGGER and r.levelno >= logging.ERROR
    ]
    assert len(errors) == 1
    message = errors[0].getMessage()
    assert str(job.id) in message
    assert str(node.id) in message
    assert str(tenant) in message


def test_complete_logs_no_error_when_the_assigned_node_is_found(
    caplog,
) -> None:
    import logging

    tenant = TenantId.new()
    worker, job, node = _make_running_worker_and_job_in(tenant)

    (
        service,
        _worker_repository,
        _job_repository,
        _node_repository,
        _lease_repository,
        lease,
    ) = _build_service(worker, job, node)

    with caplog.at_level(logging.ERROR, logger=_REPORT_LOGGER):
        service.complete(
            worker.id,
            job.id,
            tenant_id=tenant,
            lease_id=lease.id,
            exit_code=0,
        )

    assert [
        r
        for r in caplog.records
        if r.name == _REPORT_LOGGER and r.levelno >= logging.ERROR
    ] == []
