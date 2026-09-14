from __future__ import annotations

import logging

from app.application.services.job_execution_support import (
    reclaim_job,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.repositories.job_repository import (
    JobRepository,
)
from app.domain.repositories.lease_repository import (
    LeaseRepository,
)
from app.domain.repositories.node_repository import (
    NodeRepository,
)
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)

logger = logging.getLogger(__name__)


class RecoverExpiredLeaseService:
    """
    Recover work abandoned by expired leases.

    This application service coordinates recovery by
    restoring workers, jobs and leases to a
    consistent state after lease expiration.
    """

    def __init__(
        self,
        worker_repository: WorkerRepository,
        job_repository: JobRepository,
        lease_repository: LeaseRepository,
        node_repository: NodeRepository,
        record_job_events_service: RecordJobEventsService | None = None,
    ) -> None:
        self._worker_repository = worker_repository
        self._job_repository = job_repository
        self._lease_repository = lease_repository
        self._node_repository = node_repository
        self._record_job_events_service = record_job_events_service

    def execute(
        self,
    ) -> None:
        """
        Recover every expired lease.

        Leases that have not yet expired are left untouched;
        their worker is still the legitimate owner of the job.

        The lease row is deleted first, before the job or
        worker are touched. This closes the window where a
        worker's background renewal thread could successfully
        renew a lease that reconciliation has already decided
        to reclaim -- if delete ran last, a renewal landing
        between job.reclaim() and delete() would succeed
        against a lease that's effectively already gone,
        letting a worker believe it still owns a job that's
        about to be (or already has been) handed to someone
        else.

        A job whose lease expired is reclaimed rather than
        unscheduled: it may be SCHEDULED (worker died before
        starting it) or, far more commonly, RUNNING (worker
        died mid-execution, which is the normal case since a
        lease stays alive for the job's entire runtime).
        reclaim() consumes a retry attempt and fails the job
        outright once retries are exhausted, so a
        consistently unhealthy worker cannot cause a job to
        be reassigned and abandoned forever.

        A job may also no longer be in a reclaimable state at
        all by the time its lease expires -- for example, it
        left SCHEDULED via the scheduler's own unschedule()
        path (see NoAvailableNodeError handling) before this
        lease's TTL ran out. That's not an error: the lease
        row is already gone (deleted above) and there's
        nothing left to reconcile for this job, so we log and
        move on rather than letting one stale lease crash the
        entire reconciliation pass.
        """
        for lease in self._lease_repository.list():
            if not lease.is_expired():
                continue

            worker = self._worker_repository.get_by_id(
                lease.worker_id,
            )
            job = self._job_repository.get_by_id(
                lease.job_id,
            )

            if job is None:
                self._lease_repository.delete(
                    lease.job_id,
                )

                if worker is not None:
                    worker.recover()
                    self._worker_repository.save(
                        worker,
                    )

                continue

            if worker is not None:
                worker.recover()
                self._worker_repository.save(
                    worker,
                )

            was_cancelling = job.is_cancelling()

            node = None
            if job.assigned_node_id is not None:
                node = self._node_repository.get_by_id(
                    job.assigned_node_id,
                )

            reclaimed = reclaim_job(
                job,
                node,
                lease_repository=self._lease_repository,
                node_repository=self._node_repository,
                job_repository=self._job_repository,
            )

            if not reclaimed:
                logger.warning(
                    "Skipping reclaim for job %s: lease expired but"
                    "job is no longer in a reclaimable state "
                    "(status=%s). Stale lease row has already been "
                    "deleted.",
                    job.id,
                    job.status,
                )
                continue

            if self._record_job_events_service is not None:
                event_type = (
                    "JobCancelled"
                    if was_cancelling
                    else "JobReclaimed"
                )
                self._record_job_events_service.record(
                    aggregate_id=str(job.id),
                    event_type=event_type,
                )
