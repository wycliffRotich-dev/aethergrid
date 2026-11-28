from __future__ import annotations

import copy
import threading
from collections.abc import Callable

import pytest

from app.application.services.cancel_job_service import (
    CancelJobService,
)
from app.domain.entities.job import Job
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.enums.job_status import JobStatus
from app.domain.exceptions.invalid_job_transition import (
    InvalidJobTransition,
)
from app.domain.exceptions.job_status_conflict_error import (
    JobStatusConflictError,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from tests.support.jobs import make_job


def test_cancel_job_service_cancels_a_queued_job() -> None:
    """
    A queued job can be cancelled.
    """

    job = make_job(
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
        DEFAULT_TENANT_ID,
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
    job = make_job(
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
        DEFAULT_TENANT_ID,
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
    job = make_job(
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
        DEFAULT_TENANT_ID,
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
        DEFAULT_TENANT_ID,
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
    job = make_job(
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
            DEFAULT_TENANT_ID,
        )

    assert job.status == JobStatus.COMPLETED


def test_cancel_job_service_raises_for_already_failed_job() -> None:
    """
    Same reasoning as the COMPLETED case: a FAILED job's
    outcome is already settled and must not be overwritten
    by a stale or duplicate cancel request.
    """
    job = make_job(
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
            DEFAULT_TENANT_ID,
        )

    assert job.status == JobStatus.FAILED


def test_cancel_job_service_raises_for_already_cancelled_job() -> None:
    """
    A job already CANCELLED has nothing left to cancel. A
    duplicate cancel request (e.g. a retried client call)
    must not be treated as a second, silent success.
    """
    job = make_job(
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
            DEFAULT_TENANT_ID,
        )

    assert job.status == JobStatus.CANCELLED


class _InterleavingJobRepository(InMemoryJobRepository):
    """
    Runs a one-shot concurrent mutation right after CancelJobService
    reads a job and before it writes back, exposing the race window
    between get_by_id and save_if_unchanged.
    """

    def __init__(
        self,
        jobs: list[Job],
        on_first_read: Callable[[InMemoryJobRepository], None],
    ) -> None:
        self.write_attempts = 0
        super().__init__(jobs)
        self.write_attempts = 0
        self._on_first_read = on_first_read
        self._fired = False

    def get_by_id(
        self,
        job_id: JobId,
        tenant_id: TenantId,
    ) -> Job | None:
        job = super().get_by_id(job_id, tenant_id)
        if job is None:
            return None
        snapshot = copy.deepcopy(job)
        if not self._fired:
            self._fired = True
            self._on_first_read(self)
        return snapshot

    def save(self, job: Job) -> None:
        self.write_attempts += 1
        super().save(job)

    def save_if_unchanged(
        self,
        job: Job,
        expected: Job,
    ) -> bool:
        self.write_attempts += 1
        return super().save_if_unchanged(job, expected)


def test_cancel_after_concurrent_completion_does_not_revert_settled_job() -> (
    None
):
    """
    ADR 0106: if a RUNNING job finishes and saves COMPLETED after
    CancelJobService read RUNNING, the cancel request must refuse to
    overwrite COMPLETED with CANCELLING, re-read COMPLETED, and raise
    InvalidJobTransition.
    """
    job = make_job()
    job.queue()
    job.assign_to(NodeId.new())
    job.start()

    def worker_completes_job(repo: InMemoryJobRepository) -> None:
        finished = copy.deepcopy(job)
        finished.complete(exit_code=0)
        InMemoryJobRepository.save(repo, finished)

    repository = _InterleavingJobRepository([job], worker_completes_job)
    service = CancelJobService(repository)

    with pytest.raises(InvalidJobTransition):
        service.execute(job.id, DEFAULT_TENANT_ID)

    stored = InMemoryJobRepository.get_by_id(
        repository,
        job.id,
        DEFAULT_TENANT_ID,
    )
    assert stored is not None
    assert stored.status == JobStatus.COMPLETED
    assert stored.cancellation_requested_at is None


def test_cancel_when_scheduled_job_starts_concurrently_requests_cancellation() -> (
    None
):
    """
    ADR 0106: if a SCHEDULED job transitions to RUNNING after
    CancelJobService read SCHEDULED, the service must not force an
    immediate CANCELLED onto the live subprocess. It re-reads RUNNING
    and moves the job to CANCELLING instead (ADR 0029).
    """
    job = make_job()
    job.queue()
    job.assign_to(NodeId.new())

    def worker_starts_job(repo: InMemoryJobRepository) -> None:
        started = copy.deepcopy(job)
        started.start()
        InMemoryJobRepository.save(repo, started)

    repository = _InterleavingJobRepository([job], worker_starts_job)
    service = CancelJobService(repository)

    result = service.execute(job.id, DEFAULT_TENANT_ID)

    assert result is not None
    assert result.status == JobStatus.CANCELLING
    stored = InMemoryJobRepository.get_by_id(
        repository,
        job.id,
        DEFAULT_TENANT_ID,
    )
    assert stored is not None
    assert stored.status == JobStatus.CANCELLING
    assert stored.cancellation_requested_at is not None


def test_cancel_after_retry_cycle_does_not_clobber_new_attempt_fields() -> (
    None
):
    """
    ADR 0106: if a RUNNING job fails, retries, and starts a new attempt
    on another node after CancelJobService read attempt 0, the stale
    attempt-0 write must be refused so retry_count and assigned_node_id
    are preserved when requesting cancellation on attempt 1.
    """
    first_node = NodeId.new()
    second_node = NodeId.new()
    job = make_job(max_retries=2)
    job.queue()
    job.assign_to(first_node)
    job.start()

    def worker_fails_and_retries_on_second_node(
        repo: InMemoryJobRepository,
    ) -> None:
        retried = copy.deepcopy(job)
        retried.fail(exit_code=1)
        retried.retry()
        retried.assign_to(second_node)
        retried.start()
        InMemoryJobRepository.save(repo, retried)

    repository = _InterleavingJobRepository(
        [job],
        worker_fails_and_retries_on_second_node,
    )
    service = CancelJobService(repository)

    result = service.execute(job.id, DEFAULT_TENANT_ID)

    assert result is not None
    assert result.status == JobStatus.CANCELLING
    assert result.retry_count == 1
    assert result.assigned_node_id == second_node

    stored = InMemoryJobRepository.get_by_id(
        repository,
        job.id,
        DEFAULT_TENANT_ID,
    )
    assert stored is not None
    assert stored.status == JobStatus.CANCELLING
    assert stored.retry_count == 1
    assert stored.assigned_node_id == second_node
    assert stored.cancellation_requested_at is not None


def test_cancel_on_shared_in_memory_job_started_in_place_stays_consistent() -> (
    None
):
    """
    When a worker holds the same in-memory Job instance and calls
    start() in place before persisting, cancelling that job transitions
    both the stored object and the worker's reference to CANCELLING
    without reverting to SCHEDULED.
    """
    job = make_job()
    job.queue()
    job.assign_to(NodeId.new())

    repository = InMemoryJobRepository([job])
    job.start()

    result = CancelJobService(repository).execute(
        job.id,
        DEFAULT_TENANT_ID,
    )

    assert result is not None
    assert result.status == JobStatus.CANCELLING
    assert job.status == JobStatus.CANCELLING
    stored = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert stored is not None
    assert stored.status == JobStatus.CANCELLING


def test_concurrent_threaded_cancellations_of_queued_job_allow_only_one_winner() -> (
    None
):
    """
    Two threads cancelling the same QUEUED job simultaneously against
    InMemoryJobRepository must serialize cleanly: exactly one thread
    settles CANCELLED and the second raises InvalidJobTransition.
    """
    job = make_job()
    job.queue()
    start_gate = threading.Barrier(2)

    class _BarrierJobRepository(InMemoryJobRepository):
        def save_if_unchanged(
            self,
            candidate: Job,
            expected: Job,
        ) -> bool:
            try:
                start_gate.wait(timeout=2.0)
            except threading.BrokenBarrierError:
                pass
            return super().save_if_unchanged(candidate, expected)

    repository = _BarrierJobRepository([job])
    service = CancelJobService(repository)
    winners: list[JobStatus] = []
    conflicts: list[InvalidJobTransition] = []
    unexpected: list[BaseException] = []
    out_lock = threading.Lock()

    def invoke_cancel() -> None:
        try:
            res = service.execute(job.id, DEFAULT_TENANT_ID)
            assert res is not None
            with out_lock:
                winners.append(res.status)
        except InvalidJobTransition as exc:
            with out_lock:
                conflicts.append(exc)
        except BaseException as exc:  # pragma: no cover
            with out_lock:
                unexpected.append(exc)

    t1 = threading.Thread(target=invoke_cancel)
    t2 = threading.Thread(target=invoke_cancel)
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    assert unexpected == []
    assert winners == [JobStatus.CANCELLED]
    assert len(conflicts) == 1


def test_cancel_when_already_cancelling_performs_no_write() -> None:
    """
    A job already in CANCELLING is a pure read-only no-op so a
    concurrent terminal outcome cannot be clobbered by a redundant
    save.
    """
    job = make_job()
    job.queue()
    job.assign_to(NodeId.new())
    job.start()
    job.request_cancellation()

    repository = _InterleavingJobRepository([job], lambda _repo: None)
    service = CancelJobService(repository)

    result = service.execute(job.id, DEFAULT_TENANT_ID)

    assert result is not None
    assert result.status == JobStatus.CANCELLING
    assert repository.write_attempts == 0


def test_cancel_raises_conflict_error_when_status_retries_exhausted() -> None:
    """
    If concurrent writers change the job's state on every attempt up
    to the retry cap, execute raises JobStatusConflictError (mapped to
    HTTP 409) instead of spinning indefinitely or raising RuntimeError.
    """

    class _AlwaysContendedRepository(InMemoryJobRepository):
        def save_if_unchanged(
            self,
            job: Job,
            expected: Job,
        ) -> bool:
            return False

    job = make_job()
    job.queue()
    repository = _AlwaysContendedRepository([job])
    service = CancelJobService(repository)

    with pytest.raises(JobStatusConflictError):
        service.execute(job.id, DEFAULT_TENANT_ID)
