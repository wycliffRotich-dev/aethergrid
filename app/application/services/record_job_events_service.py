from __future__ import annotations

from app.domain.entities.event import Event
from app.domain.entities.job import Job
from app.domain.repositories.event_repository import EventRepository
from app.domain.value_objects.event_id import EventId


class RecordJobEventsService:
    """
    Application service responsible for recording
    domain events.
    """

    def __init__(
        self,
        event_repository: EventRepository,
    ) -> None:
        self._event_repository = event_repository

    def record_for_job(
        self,
        job: Job,
        event_type: str,
    ) -> Event:
        """
        Record an event about a job. The tenant is read from the job,
        so a writer cannot file an event under the wrong tenant
        (ADR 0074 decision 2).
        """
        event = Event(
            id=EventId.new(),
            aggregate_type="Job",
            aggregate_id=str(job.id),
            event_type=event_type,
            tenant_id=job.tenant_id,
        )

        self._event_repository.save(
            event,
        )

        return event
