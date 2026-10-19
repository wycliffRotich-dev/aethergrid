from __future__ import annotations

from uuid import uuid4

import pytest

from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.application.services.release_lease_service import (
    ReleaseLeaseService,
)
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.entities.worker import Worker
from app.domain.exceptions.job_not_found_error import (
    JobNotFoundError,
)
from app.domain.exceptions.lease_not_found_error import (
    LeaseNotFoundError,
)
from app.domain.exceptions.no_active_lease_error import (
    NoActiveLeaseError,
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
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node
from tests.support.workers import make_worker


def _make_worker_with_running_job() -> tuple[Worker, Job]:
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
        tenant_id=worker.tenant_id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    worker_repository = InMemoryWorkerRepository([worker])

    service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
    )

    service.execute(worker.id, lease.id)

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
        tenant_id=worker.tenant_id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    worker_repository = InMemoryWorkerRepository([worker])

    service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
    )

    service.execute(worker.id, lease.id)

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

    with pytest.raises(NoActiveLeaseError):
        service.execute(worker.id, uuid4())


def test_execute_raises_when_worker_does_not_exist() -> None:
    worker, job = _make_worker_with_running_job()

    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
        tenant_id=worker.tenant_id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    worker_repository = InMemoryWorkerRepository()

    service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
    )

    with pytest.raises(WorkerNotFoundError):
        service.execute(worker.id, lease.id)


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
        tenant_id=worker.tenant_id,
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
        job_repository=InMemoryJobRepository([job]),
    )

    service.execute(worker.id, lease.id)

    recorded = events.list(job.tenant_id)

    assert len(recorded) == 1
    assert recorded[0].event_type == "LeaseReleased"
    assert recorded[0].aggregate_id == str(job.id)
    assert recorded[0].aggregate_type == "Job"
    assert recorded[0].tenant_id == job.tenant_id


def test_the_event_takes_the_tenant_of_the_job_named_by_the_lease() -> None:
    """
    A job in a tenant other than the default is the case that tells a
    real lookup apart from a default tenant (ADR 0074 decision 2).
    """
    worker, _ = _make_worker_with_running_job()
    other_tenant = TenantId.new()
    job = make_job(tenant_id=other_tenant)

    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
        tenant_id=worker.tenant_id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    events = InMemoryEventRepository()

    service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=InMemoryWorkerRepository([worker]),
        record_job_events_service=RecordJobEventsService(
            event_repository=events,
        ),
        job_repository=InMemoryJobRepository([job]),
    )

    service.execute(worker.id, lease.id)

    recorded = events.list(other_tenant)

    assert len(recorded) == 1
    assert recorded[0].tenant_id == other_tenant
    assert recorded[0].tenant_id != DEFAULT_TENANT_ID


def test_execute_keeps_the_lease_when_the_job_cannot_be_found() -> None:
    """
    The job is looked up before the lease is deleted, so a missing
    job changes nothing and records nothing (ADR 0074).
    """
    worker, job = _make_worker_with_running_job()

    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
        tenant_id=worker.tenant_id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)

    events = InMemoryEventRepository()

    service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=InMemoryWorkerRepository([worker]),
        record_job_events_service=RecordJobEventsService(
            event_repository=events,
        ),
        job_repository=InMemoryJobRepository(),
    )

    with pytest.raises(JobNotFoundError):
        service.execute(worker.id, lease.id)

    assert lease_repository.get_by_worker_id(worker.id) is not None
    assert events.list(job.tenant_id) == []


def test_a_recorder_without_a_job_repository_is_refused() -> None:
    with pytest.raises(ValueError):
        ReleaseLeaseService(
            lease_repository=InMemoryLeaseRepository(),
            worker_repository=InMemoryWorkerRepository(),
            record_job_events_service=RecordJobEventsService(
                event_repository=InMemoryEventRepository(),
            ),
        )


def test_execute_raises_and_preserves_an_unrelated_lease_after_reclaim_and_reacquire() -> (
    None
):
    """
    Proves the fix for a real gap (ADR 0034): execute() used
    to look up whatever lease a worker currently holds by
    worker_id and delete it, without ever checking that lease
    was the same one the caller originally acquired and had
    been renewing.

    Simulates the real sequence: a worker's original lease is
    reclaimed by reconciliation (its holder went stale), and
    the same worker is later, legitimately, assigned a
    different job with a brand-new lease. A stale caller still
    holding the *first* lease's identity, finally finishing
    execution and calling release, must now be rejected rather
    than allowed to delete whatever lease happens to be on
    record, which would otherwise be the second, unrelated,
    legitimately-held lease.
    """
    worker, job = _make_worker_with_running_job()

    original_lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
        tenant_id=worker.tenant_id,
    )

    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(original_lease)

    worker_repository = InMemoryWorkerRepository([worker])

    service = ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
    )

    # Reconciliation reclaims the original lease (the worker
    # went stale from this lease's perspective)...
    lease_repository.delete(job.id)

    # ...and the same worker is legitimately re-acquired for a
    # different job, with its own new lease.
    other_job_id = JobId.new()
    replacement_lease = Lease.create(
        worker_id=worker.id,
        job_id=other_job_id,
        tenant_id=worker.tenant_id,
    )
    lease_repository.save(replacement_lease)

    # The stale caller, still believing it holds the original
    # lease, finally calls release, asserting that identity
    # explicitly.
    with pytest.raises(LeaseNotFoundError):
        service.execute(worker.id, original_lease.id)

    # The replacement lease, belonging to a different,
    # currently-legitimate job execution, must survive.
    surviving = lease_repository.get_by_worker_id(worker.id)
    assert surviving is not None
    assert surviving.id == replacement_lease.id
