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

        The lease is deleted first, before the job or worker
        are touched, via delete_if_expired() rather than an
        unconditional delete(). Ordering alone (delete-first)
        only prevents a renewal from landing after the delete;
        it does nothing about a renewal that already happened
        before it, since is_expired() above was checked against
        a snapshot read at the top of this loop, not at the
        moment of deletion. delete_if_expired() re-checks
        expiry atomically at delete time, so a lease renewed
        between the snapshot and the delete is left untouched
        instead of being stolen out from under its current,
        legitimate owner -- the same class of race ADR 0034
        fenced for ReleaseLeaseService, applied here to
        reconciliation's own reclaim path.

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

            deleted = self._lease_repository.delete_if_expired(
                lease.job_id,
            )

            if not deleted:
                # Renewed since the list() snapshot above was
                # taken -- the worker still legitimately owns
                # this lease. Nothing to reconcile for this
                # job; reclaiming it now would steal a lease
                # out from under its current, legitimate owner
                # (the exact class of bug ADR 0034 fenced for
                # release, here applied to reconciliation's own
                # delete).
                logger.info(
                    "Skipping reclaim for job %s: lease was "
                    "renewed after this pass's snapshot was "
                    "read, so it is no longer expired.",
                    lease.job_id,
                )
                continue

            worker = self._worker_repository.get_by_id(
                lease.worker_id,
            )
            job = self._job_repository.get_by_id(
                lease.job_id,
            )

            if job is None:
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
                node = self._node_repository.get_by_id_across_tenants(
                    job.assigned_node_id,
                )

            reclaimed = reclaim_job(
                job,
                node,
                lease_repository=self._lease_repository,
                node_repository=self._node_repository,
                job_repository=self._job_repository,
                lease_already_deleted=True,
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
