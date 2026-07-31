from __future__ import annotations

from app.application.services.acquire_lease_service import (
    AcquireLeaseService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.job import Job
from app.domain.entities.worker import Worker
from app.domain.exceptions.no_available_node_error import (
    NoAvailableNodeError,
)
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)


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
        record_job_events_service: RecordJobEventsService | None = None,
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

        for worker in self._worker_repository.list():
            if worker.node.id != job.assigned_node_id:
                continue

            if not worker.is_idle():
                continue

            worker.accept(job)

            if self._record_job_events_service is not None:
                self._record_job_events_service.record(
                    aggregate_id=str(job.id),
                    event_type="WorkerAssigned",
                )

            if self._acquire_lease_service is not None:
                self._acquire_lease_service.execute(
                    worker,
                    job,
                )

            worker.start()

            self._worker_repository.save(
                worker,
            )

            return worker

        raise NoAvailableNodeError(
            "No idle worker is available on the assigned node."
        )
