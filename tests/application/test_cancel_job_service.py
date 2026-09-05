import pytest

from app.application.services.cancel_job_service import (
    CancelJobService,
)
from app.domain.entities.job import Job
from app.domain.enums.job_status import JobStatus
from app.domain.exceptions.invalid_job_transition import (
    InvalidJobTransition,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)


def test_cancel_job_service_cancels_a_queued_job() -> None:
    """
    A queued job can be cancelled.
    """

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=4096,
            vram_mib=2048,
        ),
    )

    job.queue()

    repository = InMemoryJobRepository(
        [
            job,
        ],
    )

    service = CancelJobService(
        repository,
    )

    service.execute(
        job.id,
    )

    assert job.status == JobStatus.CANCELLED


def test_cancel_job_service_requests_cancellation_of_a_running_job() -> None:
    """
    A running job cannot be cancelled immediately, no
    subprocess reachable from here. It moves to CANCELLING
    instead (ADR 0029); actual termination is delivered
    later, asynchronously, on the worker's next lease
    renewal.
    """
    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=4096,
            vram_mib=2048,
        ),
    )
    job.queue()
    job.assign_to(NodeId.new())
    job.start()

    repository = InMemoryJobRepository(
        [
            job,
        ],
    )
    service = CancelJobService(
        repository,
    )

    service.execute(
        job.id,
    )

    assert job.status == JobStatus.CANCELLING
    assert job.cancellation_requested_at is not None


def test_cancel_job_service_is_idempotent_when_already_cancelling() -> None:
    """
    Cancelling a job that's already CANCELLING must not force
    it straight to CANCELLED. That would mark it cancelled
    before the subprocess is actually confirmed dead, ahead
    of the worker ever having a chance to terminate it.
    """
    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=4096,
            vram_mib=2048,
        ),
    )
    job.queue()
    job.assign_to(NodeId.new())
    job.start()
    job.request_cancellation()

    repository = InMemoryJobRepository(
        [
            job,
        ],
    )
    service = CancelJobService(
        repository,
    )

    service.execute(
        job.id,
    )

    assert job.status == JobStatus.CANCELLING


def test_cancel_job_service_returns_none_for_missing_job() -> None:
    repository = InMemoryJobRepository(
        [],
    )
    service = CancelJobService(
        repository,
    )

    result = service.execute(
        JobId.new(),
    )

    assert result is None


def test_cancel_job_service_raises_for_already_completed_job() -> None:
    """
    A job that already reached COMPLETED has a settled,
    real outcome. Forcing it to CANCELLED here would
    misreport what actually happened, so this must raise
    rather than silently succeed (see InvalidJobTransition's
    409 mapping in the jobs router).
    """
    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=4096,
            vram_mib=2048,
        ),
    )
    job.queue()
    job.assign_to(NodeId.new())
    job.start()
    job.complete()

    repository = InMemoryJobRepository(
        [
            job,
        ],
    )
    service = CancelJobService(
        repository,
    )

    with pytest.raises(InvalidJobTransition):
        service.execute(
            job.id,
        )

    assert job.status == JobStatus.COMPLETED


def test_cancel_job_service_raises_for_already_failed_job() -> None:
    """
    Same reasoning as the COMPLETED case: a FAILED job's
    outcome is already settled and must not be overwritten
    by a stale or duplicate cancel request.
    """
    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=4096,
            vram_mib=2048,
        ),
    )
    job.queue()
    job.assign_to(NodeId.new())
    job.start()
    job.fail()

    repository = InMemoryJobRepository(
        [
            job,
        ],
    )
    service = CancelJobService(
        repository,
    )

    with pytest.raises(InvalidJobTransition):
        service.execute(
            job.id,
        )

    assert job.status == JobStatus.FAILED


def test_cancel_job_service_raises_for_already_cancelled_job() -> None:
    """
    A job already CANCELLED has nothing left to cancel. A
    duplicate cancel request (e.g. a retried client call)
    must not be treated as a second, silent success.
    """
    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=4096,
            vram_mib=2048,
        ),
    )
    job.queue()
    job.cancel()

    repository = InMemoryJobRepository(
        [
            job,
        ],
    )
    service = CancelJobService(
        repository,
    )

    with pytest.raises(InvalidJobTransition):
        service.execute(
            job.id,
        )

    assert job.status == JobStatus.CANCELLED
