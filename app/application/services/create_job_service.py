from __future__ import annotations

from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.job import Job
from app.domain.repositories.job_repository import (
    JobRepository,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)


class CreateJobService:
    """
    Creates and persists a new job in the QUEUED state.

    Scheduling is intentionally not attempted here. The
    background cluster tick (see SchedulerLoopService) is
    the single source of truth for moving queued jobs onto
    nodes and assigning idle workers to them. Previously,
    this service also called SchedulerService synchronously
    at creation time, which allocated a node and marked the
    job SCHEDULED but never assigned a worker to it, since
    only SchedulerLoopService performs worker assignment.
    A job scheduled this way would reach SCHEDULED and then
    never be revisited, leaving it permanently unassigned.
    Removing the synchronous scheduling call here ensures
    every job is scheduled and assigned through the single
    code path that correctly does both.
    """

    def __init__(
        self,
        job_repository: JobRepository,
        record_job_events_service: RecordJobEventsService,
    ) -> None:
        self._job_repository = job_repository
        self._record_job_events_service = record_job_events_service

    def execute(
        self,
        resources: ResourceRequirements,
    ) -> Job:
        job = Job(
            id=JobId.new(),
            resources=resources,
        )

        job.queue()

        self._job_repository.save(
            job,
        )

        self._record_job_events_service.record(
            aggregate_id=str(job.id),
            aggregate_type="Job",
            event_type="JobCreated",
        )

        return job
