from __future__ import annotations

import logging

from app.application.services.acquire_lease_service import (
    AcquireLeaseService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.job import Job
from app.domain.entities.worker import Worker
from app.domain.exceptions.lease_tenant_mismatch_error import (
    LeaseTenantMismatchError,
)
from app.domain.exceptions.no_available_node_error import (
    NoAvailableNodeError,
)
from app.domain.exceptions.worker_not_found_error import (
    WorkerNotFoundError,
)
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)

logger = logging.getLogger(__name__)


class AssignWorkerService:
    """
    Assigns a scheduled job to an idle worker.

    Only workers that:

    - are IDLE
    - belong to the node already selected by the scheduler

    are eligible to execute the job.
    """

    def __init__(
        self,
        worker_repository: WorkerRepository,
        acquire_lease_service: AcquireLeaseService | None = None,
        record_job_events_service: RecordJobEventsService | None =None,
    ) -> None:
        self._worker_repository = worker_repository
        self._acquire_lease_service = acquire_lease_service
        self._record_job_events_service = record_job_events_service

    def execute(
        self,
        job: Job,
    ) -> Worker:
        """
        Locate an idle worker on the assigned node,
        accept the job and transition it to RUNNING.
        """
        if job.assigned_node_id is None:
            raise ValueError(
                "Job has not been assigned to a node."
            )

        for worker in self._worker_repository.list_across_tenants():
            if worker.node.id != job.assigned_node_id:
                continue

            if not worker.is_idle():
                continue

            if self._acquire_lease_service is not None:
                try:
                    self._acquire_lease_service.execute(
                        worker,
                        job,
                    )
                except WorkerNotFoundError as exc:
                    # The worker we just read as IDLE was deleted
                    # concurrently -- most likely its node went
                    # offline and was removed by
                    # RemoveOfflineNodeService, cascading the
                    # delete to this worker row (schema.sql:
                    # workers.node_id ON DELETE CASCADE). By the
                    # time the lease insert ran, the worker no
                    # longer existed. From the scheduler's
                    # perspective this is indistinguishable from
                    # "no idle worker was actually available", so
                    # it's reported the same way: the caller
                    # (SchedulerLoopService) already knows how to
                    # unschedule the job and retry it on the next
                    # tick.
                    raise NoAvailableNodeError(
                        "No idle worker is available on the "
                        "assigned node."
                    ) from exc
                except LeaseTenantMismatchError as exc:
                    # The scheduler never pairs a job with a node
                    # of another tenant (ADR 0064 point 6), so
                    # this is a bug upstream, and it is logged as
                    # one. It is reported like any refused
                    # assignment so the scheduler unschedules the
                    # job and releases the node. Left to escape,
                    # it would leave the job SCHEDULED with no
                    # lease and no worker holding it, and neither
                    # the scheduler's QUEUED query nor the lease
                    # and offline-node recovery reaches such a job
                    # (ADR 0075).
                    logger.error(
                        "Refused a lease across tenants for job "
                        "%s and worker %s.",
                        job.id,
                        worker.id,
                    )
                    raise NoAvailableNodeError(
                        "No idle worker is available on the "
                        "assigned node."
                    ) from exc

            # The worker accepts the job only after the lease is
            # held. accept() cannot refuse here, because the loop
            # above already checked that the worker is idle and on
            # the job's node. Accepting first would leave a worker
            # BUSY with a job it holds no lease for whenever the
            # lease is refused, in any repository that hands back
            # the stored object (ADR 0075).
            worker.accept(job)

            # Deliberately does not call worker.start() here.
            # Assignment means "this worker now holds the job",
            # not "execution has begun" -- those used to be the
            # same instant when execution happened synchronously
            # in this same process. With a real agent (ADR 0019),
            # there's a real network hop between the two, and the
            # job must stay SCHEDULED until the agent that's
            # actually running it confirms it has (the future
            # /workers/{worker_id}/jobs/{job_id}/start endpoint).
            # Reporting RUNNING before that would be the system
            # lying about its own state.

            self._worker_repository.save(
                worker,
            )

            if self._record_job_events_service is not None:
                self._record_job_events_service.record_for_job(
                    job,
                    event_type="WorkerAssigned",
                )

            return worker

        raise NoAvailableNodeError(
            "No idle worker is available on the assigned node."
        )
