from __future__ import annotations

import copy
import logging
import time
from collections.abc import Callable

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
from app.domain.value_objects.worker_id import WorkerId

logger = logging.getLogger(__name__)

# The workers that hold a job, by the job's tenant and id.
_Holders = dict[tuple[TenantId, JobId], list[tuple[TenantId, WorkerId]]]

# The states in which a job must be held through a lease. A job in
# another state is waiting (QUEUED) or finished, and holds none.
_LEASED_STATUSES = frozenset(
    {
        JobStatus.SCHEDULED,
        JobStatus.RUNNING,
        JobStatus.CANCELLING,
    }
)

# How long a job must have gone without a lease before it counts as
# abandoned (ADR 0096). An operation that is still running can leave a
# job without a lease for a while: an outcome report and the scheduler
# each make several repository calls in a row, and each call can wait
# up to 30 seconds for a connection from the pool. No exact bound
# exists, so this is a heuristic with a margin of six such waits. The
# reclaim is a fenced write that is safe when the heuristic is wrong.
MIN_LEASELESS_AGE_SECONDS = 180.0

# The longest gap between two passes that still counts as continuous
# observation. The tick runs every second. A longer gap means the
# process stopped leading or stalled, and a job seen before the gap
# says nothing about the time inside it.
MAX_PASS_GAP_SECONDS = 30.0


class RecoverLeaselessJobService:
    """
    Recover a job that is held by no lease (ADR 0096).

    A job in SCHEDULED, RUNNING or CANCELLING holds a lease row, or is
    being written by an operation that is still running. This service
    repairs a job that has held no lease for longer than
    MIN_LEASELESS_AGE_SECONDS and whose writer is gone.

    An abandoned job and an in-flight job look the same to it. Three
    writers produce a job in one of those states with no lease row,
    and only the first leaves it behind when it stops:

    1. Expired-lease recovery deletes the lease, then saves the
       worker, the job and the node in separate writes.
    2. The scheduler saves the job as SCHEDULED before its lease
       exists.
    3. An outcome report releases the lease, saves the worker, and
       then saves the job and the node.

    The service therefore waits, and then reclaims with one fenced
    write that applies only if the job still has the status that was
    read and no lease row exists (JobRepository.save_if_leaseless).
    The node is released after the job is saved (ADR 0092), so
    running the repair twice cannot over-report capacity.

    Each pass reads every lease, every job and, only when a job is
    ready to reclaim, every worker, across all tenants.

    The first-seen times are held in memory. They are cleared when a
    read fails and when the previous pass ended too long ago, so an
    old sighting is never joined to a new one across a gap. A process
    that restarts loses them and costs one more minimum age.
    """

    def __init__(
        self,
        job_repository: JobRepository,
        lease_repository: LeaseRepository,
        worker_repository: WorkerRepository,
        node_repository: NodeRepository,
        record_job_events_service: RecordJobEventsService | None = None,
        clock: Callable[[], float] = time.monotonic,
        min_age_seconds: float = MIN_LEASELESS_AGE_SECONDS,
        max_pass_gap_seconds: float = MAX_PASS_GAP_SECONDS,
    ) -> None:
        self._job_repository = job_repository
        self._lease_repository = lease_repository
        self._worker_repository = worker_repository
        self._node_repository = node_repository
        self._record_job_events_service = record_job_events_service
        self._clock = clock
        self._min_age = min_age_seconds
        self._max_pass_gap = max_pass_gap_seconds
        # First time each job was seen without a lease, and its status
        # then. A job whose status changed starts again.
        self._first_seen: dict[
            tuple[TenantId, JobId], tuple[float, JobStatus]
        ] = {}
        self._last_pass_ended: float | None = None

    def execute(
        self,
    ) -> None:
        """
        Reclaim every job that has held no lease for the minimum age.

        One job that cannot be reclaimed does not stop the others.
        """
        now = self._clock()

        if (
            self._last_pass_ended is None
            or now - self._last_pass_ended > self._max_pass_gap
        ):
            self._first_seen.clear()

        try:
            leased = {
                (lease.tenant_id, lease.job_id)
                for lease in self._lease_repository.list_across_tenants()
            }
            jobs = self._job_repository.list_across_tenants()
        except Exception:
            # A pass that does not run to completion proves nothing
            # about the time it missed.
            self._first_seen.clear()
            self._last_pass_ended = None
            raise

        seen: dict[tuple[TenantId, JobId], JobStatus] = {
            (job.tenant_id, job.id): job.status
            for job in jobs
            if job.status in _LEASED_STATUSES
            and (job.tenant_id, job.id) not in leased
        }

        first_seen: dict[tuple[TenantId, JobId], tuple[float, JobStatus]] = {}
        for key, status in seen.items():
            earlier = self._first_seen.get(key)
            first_seen[key] = (
                earlier
                if earlier is not None and earlier[1] is status
                else (now, status)
            )
        self._first_seen = first_seen

        ready = [
            (key, status)
            for key, (since, status) in first_seen.items()
            if now - since >= self._min_age
        ]

        if ready:
            holders = self._workers_holding_a_job()

            for (tenant_id, job_id), status in ready:
                try:
                    self._recover(tenant_id, job_id, status, holders)
                except Exception:
                    logger.exception(
                        "Could not finish recovering job %s, which held "
                        "no lease. If it is still without one, the next "
                        "pass tries again.",
                        job_id,
                    )

        self._last_pass_ended = self._clock()

    def _workers_holding_a_job(
        self,
    ) -> _Holders:
        """
        Index the workers by the job each one holds, with one read.
        """
        holders: _Holders = {}

        for worker in self._worker_repository.list_across_tenants():
            held = worker.running_job

            if held is None:
                continue

            holders.setdefault((held.tenant_id, held.id), []).append(
                (worker.tenant_id, worker.id)
            )

        return holders

    def _recover(
        self,
        tenant_id: TenantId,
        job_id: JobId,
        status: JobStatus,
        holders: _Holders,
    ) -> None:
        """
        Reclaim one job, after checking again that it is in the status
        it was first seen in and still has no lease.
        """
        stored = self._job_repository.get_by_id(
            job_id,
            tenant_id,
        )

        if stored is None or stored.status is not status:
            return

        if (
            self._lease_repository.get_by_job_id(
                job_id,
                tenant_id,
            )
            is not None
        ):
            return

        # Job.reclaim() changes the object it is called on, and a
        # repository may hand back the one it stores. The fenced
        # write decides whether the change is kept.
        job = copy.deepcopy(stored)
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
            fence_status=status,
        )

        if not reclaimed:
            logger.info(
                "Job %s changed or got a lease while it was being "
                "reclaimed, so it was left as it is.",
                job_id,
            )
            return

        logger.warning(
            "Reclaimed job %s, which was %s and held no lease.",
            job_id,
            status,
        )

        self._free_workers_holding(job, holders)
        self._record(job, was_cancelling)

    def _free_workers_holding(
        self,
        job: Job,
        holders: _Holders,
    ) -> None:
        """
        Free a worker that still holds the reclaimed job.

        Each worker is read again before it is changed, and is reset
        only if it still holds this job. A worker is never reset for
        a job that was not reclaimed.
        """
        for worker_tenant, worker_id in holders.get(
            (job.tenant_id, job.id), []
        ):
            try:
                worker = self._worker_repository.get_by_id(
                    worker_id,
                    worker_tenant,
                )

                held = worker.running_job if worker is not None else None

                if worker is None or held is None or held.id != job.id:
                    continue

                worker.recover()

                self._worker_repository.save(
                    worker,
                )
            except Exception:
                logger.exception(
                    "Job %s was reclaimed, but worker %s could not be "
                    "freed. Expired-lease and offline-node recovery do "
                    "not look for it.",
                    job.id,
                    worker_id,
                )

    def _record(
        self,
        job: Job,
        was_cancelling: bool,
    ) -> None:
        if self._record_job_events_service is None:
            return

        try:
            self._record_job_events_service.record_for_job(
                job,
                event_type=(
                    "JobCancelled" if was_cancelling else "JobReclaimed"
                ),
            )
        except Exception:
            # The job is already saved, so it is not tried again and
            # the event is lost. The two older recovery services have
            # the same gap between the job save and the event.
            logger.exception(
                "Job %s was reclaimed, but its event was not recorded "
                "and will not be retried.",
                job.id,
            )
