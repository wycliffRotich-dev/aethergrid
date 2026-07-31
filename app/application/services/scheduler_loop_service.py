from __future__ import annotations

from app.application.services.assign_worker_service import (
    AssignWorkerService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.enums.job_status import JobStatus
from app.domain.repositories.job_repository import (
    JobRepository,
)
from app.domain.repositories.node_repository import (
    NodeRepository,
)
from app.domain.services.scheduler import Scheduler


class SchedulerLoopService:
    """
    Application service responsible for scheduling queued jobs
    onto healthy nodes and assigning workers.
    """

    def __init__(
        self,
        job_repository: JobRepository,
        node_repository: NodeRepository,
        scheduler: Scheduler,
        assign_worker_service: AssignWorkerService | None = None,
        record_job_events_service: RecordJobEventsService | None = None,
    ) -> None:
        self._job_repository = job_repository
        self._node_repository = node_repository
        self._scheduler = scheduler
        self._assign_worker_service = assign_worker_service
        self._record_job_events_service = record_job_events_service

    def execute(
        self,
    ) -> None:
        """
        Schedule queued jobs in priority order.
        """
        nodes = self._node_repository.list_available()

        queued_jobs = sorted(
            (
                job
                for job in self._job_repository.list()
                if job.status == JobStatus.QUEUED
            ),
            key=lambda job: job.priority,
            reverse=True,
        )

        for job in queued_jobs:
            node = self._scheduler.select_node(
                job,
                nodes,
            )

            if node is None:
                continue

            node.allocate(
                job.resources,
            )

            job.assign_to(
                node.id,
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
                    event_type="JobScheduled",
                )

            if self._assign_worker_service is not None:
                self._assign_worker_service.execute(
                    job,
                )
