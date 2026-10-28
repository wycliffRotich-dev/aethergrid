from __future__ import annotations

import logging
from uuid import UUID

from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.application.services.release_lease_service import (
    ReleaseLeaseService,
)
from app.domain.entities.job import Job
from app.domain.entities.worker import Worker
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
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId

logger = logging.getLogger(__name__)


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
        tenant_id: TenantId,
    ) -> tuple[Worker, Job]:
        worker = self._worker_repository.get_by_id(
            worker_id,
            tenant_id,
        )

        # A worker belongs to the tenant of its node. One in
        # another tenant is a missing worker, and this runs before
        # the job check, the lease check and every write (ADR 0073
        # Decision 4).
        if worker is None or worker.node.tenant_id != tenant_id:
            raise WorkerNotFoundError(worker_id)

        # The job is read here, before the caller changes the
        # worker's state, because complete(), fail() and
        # cancel_job() all clear running_job.
        job = worker.running_job

        if job is None or job.id != job_id:
            raise WorkerJobMismatchError(
                f"Worker '{worker_id}' does not currently "
                f"hold job '{job_id}'."
            )

        return worker, job

    def _finish(
        self,
        worker: Worker,
        worker_id: WorkerId,
        job: Job,
        event_type: str,
        expected_lease_id: UUID,
        tenant_id: TenantId,
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
            tenant_id=tenant_id,
        )

        self._worker_repository.save(
            worker,
        )

        if job.assigned_node_id is not None:
            node = self._node_repository.get_by_id(
                job.assigned_node_id,
                tenant_id,
            )

            if node is not None:
                node.release(
                    job.resources,
                )

                self._node_repository.save(
                    node,
                )
            else:
                # On Postgres a job's node is always in the job's tenant,
                # and deleting a node clears the link, so this state means
                # a mistake upstream (ADR 0075 decision 14).
                logger.error(
                    "Job %s is assigned to node %s, but that node was not "
                    "found in tenant %s. The node release was skipped.",
                    job.id,
                    job.assigned_node_id,
                    tenant_id,
                )

        self._job_repository.save(
            job,
        )

        if self._record_job_events_service is not None:
            self._record_job_events_service.record_for_job(
                job,
                event_type=event_type,
            )

        return worker

    def complete(
        self,
        worker_id: WorkerId,
        job_id: JobId,
        tenant_id: TenantId,
        lease_id: UUID,
        exit_code: int | None = None,
    ) -> Worker:
        """
        Report that a job completed successfully.

        lease_id (ADR 0036) is the caller's own belief about
        which lease it holds, not a value this service looks
        up on the caller's behalf. Fencing only works if the
        value being checked came from outside; looking it up
        internally, as this service used to, can never
        disagree with itself.

        Raises:
            WorkerNotFoundError: the worker does not exist.
            WorkerJobMismatchError: the worker does not
                currently hold job_id as its running_job.
            NoActiveLeaseError, LeaseNotFoundError: lease
                release failed -- either reconciliation
                already reclaimed this job, or the caller's
                lease_id no longer matches what is actually
                current (ADR 0036). Nothing is persisted.
        """
        worker, job = self._get_owning_worker(
            worker_id,
            job_id,
            tenant_id,
        )

        worker.complete(
            exit_code=exit_code,
        )

        return self._finish(
            worker,
            worker_id,
            job,
            event_type="JobCompleted",
            expected_lease_id=lease_id,
            tenant_id=tenant_id,
        )

    def fail(
        self,
        worker_id: WorkerId,
        job_id: JobId,
        tenant_id: TenantId,
        lease_id: UUID,
        exit_code: int | None = None,
    ) -> Worker:
        """
        Report that a job failed.

        Raises the same exceptions as complete(), for the
        same reasons.
        """
        worker, job = self._get_owning_worker(
            worker_id,
            job_id,
            tenant_id,
        )

        worker.fail(
            exit_code=exit_code,
        )

        return self._finish(
            worker,
            worker_id,
            job,
            event_type="JobFailed",
            expected_lease_id=lease_id,
            tenant_id=tenant_id,
        )

    def cancel(
        self,
        worker_id: WorkerId,
        job_id: JobId,
        tenant_id: TenantId,
        lease_id: UUID,
        exit_code: int | None = None,
    ) -> Worker:
        """
        Report that a job's cancellation was confirmed: its
        subprocess was actually terminated (ADR 0029).

        Raises the same exceptions as complete()/fail(), for
        the same reasons.
        """
        worker, job = self._get_owning_worker(
            worker_id,
            job_id,
            tenant_id,
        )

        worker.cancel_job(
            exit_code=exit_code,
        )

        return self._finish(
            worker,
            worker_id,
            job,
            event_type="JobCancelled",
            expected_lease_id=lease_id,
            tenant_id=tenant_id,
        )
