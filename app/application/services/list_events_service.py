from __future__ import annotations

from app.domain.entities.event import Event
from app.domain.repositories.event_repository import (
    EventRepository,
)


class ListEventsService:
    """
    Returns every recorded domain event, across every
    aggregate, in the order they occurred.

    This backs the live event feed: unlike
    GetJobHistoryService, which scopes to a single job's
    aggregate_id, this is the cluster-wide view, every
    JobCreated, JobScheduled, WorkerAssigned, LeaseAcquired,
    LeaseReleased, JobCompleted/JobFailed, and JobReclaimed
    event, from every job and worker, interleaved
    chronologically.
    """

    def __init__(
        self,
        event_repository: EventRepository,
    ) -> None:
        self._event_repository = event_repository

    def execute(
        self,
    ) -> list[Event]:
        """
        Return every recorded event, ordered by occurrence.
        """
        return self._event_repository.list()
