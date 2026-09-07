from __future__ import annotations

from uuid import UUID

from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.application.services.release_lease_service import (
    ReleaseLeaseService,
)
from app.domain.entities.job import Job
from app.domain.entities.worker import Worker
from app.domain.exceptions.no_active_lease_error import (
    NoActiveLeaseError,
)
from app.domain.exceptions.worker_job_mismatch_error import (
    WorkerJobMismatchError,
)
from app.domain.exceptions.worker_not_found_error import (
    WorkerNotFoundError,
)
from app.domain.repositories.job_repository import JobRepository
from app.domain.repositories.lease_repository import (
    LeaseRepository,
)
from app.domain.repositories.node_repository import NodeRepository
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.worker_id import WorkerId


class ReportJobOutcomeService:
    """
    Records a job's real outcome, as reported by whatever
    actually executed it, today the same process, eventually
    a real agent (ADR 0019).

    Mirrors WorkerExecutionLoop's own post-execution block
    exactly, including its ordering: the lease is released
    before anything is persisted, not after. If lease release
    fails, that means reconciliation already reclaimed this
    job and handed it to someone else (ADR 0011); this
    caller's outcome is real but no longer canonical, and
    must not be persisted at all, the same "drop it on the
    floor" principle WorkerExecutionLoop already applies to a
    lost lease during renewal. Nothing here is saved unless
    lease release succeeds first.
    """

    def __init__(
        self,
        worker_repository: WorkerRepository,
        job_repository: JobRepository,
        node_repository: NodeRepository,
        lease_repository: LeaseRepository,
        release_lease_service: ReleaseLeaseService,
        record_job_events_service: RecordJobEventsService | None = None,
    ) -> None:
        self._worker_repository = worker_repository
        self._job_repository = job_repository
        self._node_repository = node_repository
        self._lease_repository = lease_repository
        self._release_lease_service = release_lease_service
        self._record_job_events_service = record_job_events_service

    def _get_owning_worker(
        self,
        worker_id: WorkerId,
        job_id: JobId,
    ) -> Worker:
        worker = self._worker_repository.get_by_id(
            worker_id,
        )

        if worker is None:
            raise WorkerNotFoundError(worker_id)

        if (
            worker.running_job is None
            or worker.running_job.id != job_id
        ):
            raise WorkerJobMismatchError(
                f"Worker '{worker_id}' does not currently "
                f"hold job '{job_id}'."
            )

        return worker

    def _current_lease_id(
        self,
        worker_id: WorkerId,
    ) -> UUID:
        # Captured immediately before _finish() releases the
        # lease, so release_lease_service can verify this is
        # still the same lease this call started with, not
        # just "some lease this worker happens to hold right
        # now" (ADR 0034). Narrower window than
        # WorkerExecutionLoop's, since this is one request's
        # handling time rather than a whole execution's
        # lifetime, but the same real gap: without this,
        # a stale or delayed outcome report could delete a
        # different, legitimately-held lease out from under
        # whoever actually holds it.
        lease = self._lease_repository.get_by_worker_id(
            worker_id,
        )

        if lease is None:
            raise NoActiveLeaseError(worker_id)

        return lease.id

    def _finish(
        self,
        worker: Worker,
        worker_id: WorkerId,
        job: Job,
        event_type: str,
        expected_lease_id: UUID,
    ) -> Worker:
        # job is passed in explicitly, captured by the caller
        # before worker.complete()/worker.fail() ran -- both
        # already cleared worker.running_job to None by the
        # time this method runs, so re-deriving it here from
        # worker.running_job would resolve to None instead of
        # the job that just finished.

        # Release the lease, and persist the worker as IDLE,
        # before persisting the job's terminal status -- same
        # ordering, and the same two races it avoids, as
        # WorkerExecutionLoop.
        self._release_lease_service.execute(
            worker_id,
            expected_lease_id,
        )

        self._worker_repository.save(
            worker,
        )

        if job.assigned_node_id is not None:
            node = self._node_repository.get_by_id(
                job.assigned_node_id,
            )

            if node is not None:
                node.release(
                    job.resources,
                )

                self._node_repository.save(
                    node,
                )

        self._job_repository.save(
            job,
        )

        if self._record_job_events_service is not None:
            self._record_job_events_service.record(
                aggregate_id=str(job.id),
                event_type=event_type,
            )

        return worker

    def complete(
        self,
        worker_id: WorkerId,
        job_id: JobId,
        exit_code: int | None = None,
    ) -> Worker:
        """
        Report that a job completed successfully.

        Raises:
            WorkerNotFoundError: the worker does not exist.
            WorkerJobMismatchError: the worker does not
                currently hold job_id as its running_job.
            NoActiveLeaseError, LeaseNotFoundError: lease
                release failed -- reconciliation already
                reclaimed this job. Nothing is persisted.
        """
        worker = self._get_owning_worker(
            worker_id,
            job_id,
        )

        lease_id = self._current_lease_id(worker_id)

        job = worker.running_job

        worker.complete(
            exit_code=exit_code,
        )

        return self._finish(
            worker,
            worker_id,
            job,
            event_type="JobCompleted",
            expected_lease_id=lease_id,
        )

    def fail(
        self,
        worker_id: WorkerId,
        job_id: JobId,
        exit_code: int | None = None,
    ) -> Worker:
        """
        Report that a job failed.

        Raises the same exceptions as complete(), for the
        same reasons.
        """
        worker = self._get_owning_worker(
            worker_id,
            job_id,
        )

        lease_id = self._current_lease_id(worker_id)

        job = worker.running_job

        worker.fail(
            exit_code=exit_code,
        )

        return self._finish(
            worker,
            worker_id,
            job,
            event_type="JobFailed",
            expected_lease_id=lease_id,
        )

    def cancel(
        self,
        worker_id: WorkerId,
        job_id: JobId,
        exit_code: int | None = None,
    ) -> Worker:
        """
        Report that a job's cancellation was confirmed: its
        subprocess was actually terminated (ADR 0029).

        Raises the same exceptions as complete()/fail(), for
        the same reasons.
        """
        worker = self._get_owning_worker(
            worker_id,
            job_id,
        )

        lease_id = self._current_lease_id(worker_id)

        job = worker.running_job

        worker.cancel_job(
            exit_code=exit_code,
        )

        return self._finish(
            worker,
            worker_id,
            job,
            event_type="JobCancelled",
            expected_lease_id=lease_id,
        )
