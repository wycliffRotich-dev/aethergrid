from __future__ import annotations

import logging

from app.application.services.job_execution_support import (
    reclaim_job,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.job import Job
from app.domain.enums.job_status import JobStatus
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
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId

logger = logging.getLogger(__name__)

# The states in which a job must be held through a lease. A job in
# another state is waiting (QUEUED) or finished, and holds none.
_LEASED_STATUSES = frozenset(
    {
        JobStatus.SCHEDULED,
        JobStatus.RUNNING,
        JobStatus.CANCELLING,
    }
)


class RecoverLeaselessJobService:
    """
    Recover a job that is held by no lease (ADR 0096).

    Every other recovery path starts from a lease row or from an
    offline node. Recovering an expired lease deletes the row first
    and changes the job, the worker and the node afterwards, each in
    its own write. A crash or an error between the delete and the job
    save leaves a SCHEDULED, RUNNING or CANCELLING job with no lease:
    the next pass lists leases, so it never sees the job, the
    scheduler only reads QUEUED jobs, and offline-node recovery only
    reads jobs on a node that stopped sending heartbeats. The job
    stays where it is and its node keeps the capacity allocated.

    This service starts from the jobs instead. A job that should hold
    a lease and has none is reclaimed through reclaim_job, the same
    path every other recovery uses, so it consumes a retry and ends
    FAILED once retries are exhausted.

    A job is reclaimed only when it is found without a lease in two
    passes in a row. Reporting an outcome releases the lease before it
    saves the job, and the scheduler saves a job as SCHEDULED before
    its lease is acquired. A job read in either window has no lease
    for a moment and is not abandoned. Such a window closes within one
    request, and it does not survive from one pass to the next, so the
    second sighting separates the two. The candidates are read again
    before the reclaim, so a job that moved on in between is left
    alone.
    """

    def __init__(
        self,
        job_repository: JobRepository,
        lease_repository: LeaseRepository,
        worker_repository: WorkerRepository,
        node_repository: NodeRepository,
        record_job_events_service: RecordJobEventsService | None = None,
    ) -> None:
        self._job_repository = job_repository
        self._lease_repository = lease_repository
        self._worker_repository = worker_repository
        self._node_repository = node_repository
        self._record_job_events_service = record_job_events_service
        self._suspects: set[tuple[TenantId, JobId]] = set()

    def execute(
        self,
    ) -> None:
        """
        Reclaim every job that has been without a lease for two
        passes.

        The state held between passes is only the list of jobs seen
        without a lease. A process that restarts loses it, and the
        cost is one more pass before a job is reclaimed.

        One job that cannot be reclaimed does not stop the others.
        It stays a suspect and is tried again on the next pass.
        """
        leased = {
            (lease.tenant_id, lease.job_id)
            for lease in self._lease_repository.list_across_tenants()
        }

        seen: set[tuple[TenantId, JobId]] = {
            (job.tenant_id, job.id)
            for job in self._job_repository.list_across_tenants()
            if job.status in _LEASED_STATUSES
            and (job.tenant_id, job.id) not in leased
        }

        confirmed = seen & self._suspects
        self._suspects = seen

        for tenant_id, job_id in confirmed:
            try:
                reclaimed = self._recover(tenant_id, job_id)
            except Exception:
                logger.exception(
                    "Could not recover job %s, which holds no lease. "
                    "It is tried again on the next pass.",
                    job_id,
                )
                continue

            if reclaimed:
                self._suspects.discard((tenant_id, job_id))

    def _recover(
        self,
        tenant_id: TenantId,
        job_id: JobId,
    ) -> bool:
        """
        Reclaim one job, after checking again that it is still
        without a lease. Return True when it was reclaimed.
        """
        job = self._job_repository.get_by_id(
            job_id,
            tenant_id,
        )

        if job is None or job.status not in _LEASED_STATUSES:
            return False

        if (
            self._lease_repository.get_by_job_id(
                job_id,
                tenant_id,
            )
            is not None
        ):
            return False

        logger.warning(
            "Job %s is %s and holds no lease. Reclaiming it.",
            job.id,
            job.status,
        )

        self._recover_worker_holding(job)

        was_cancelling = job.is_cancelling()

        node = None
        if job.assigned_node_id is not None:
            node = self._node_repository.get_by_id(
                job.assigned_node_id,
                tenant_id,
            )

        reclaimed = reclaim_job(
            job,
            node,
            lease_repository=self._lease_repository,
            node_repository=self._node_repository,
            job_repository=self._job_repository,
            lease_already_deleted=True,
        )

        if reclaimed and self._record_job_events_service is not None:
            self._record_job_events_service.record_for_job(
                job,
                event_type=(
                    "JobCancelled" if was_cancelling else "JobReclaimed"
                ),
            )

        return reclaimed

    def _recover_worker_holding(
        self,
        job: Job,
    ) -> None:
        """
        Free a worker that still holds the job.

        A worker is reset only when it holds this job. Without a
        lease it cannot be running it as the owner.
        """
        for worker in self._worker_repository.list_across_tenants():
            held = worker.running_job

            if held is None or held.id != job.id:
                continue

            worker.recover()

            self._worker_repository.save(
                worker,
            )
