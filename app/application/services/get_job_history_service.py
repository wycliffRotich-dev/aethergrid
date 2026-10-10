from __future__ import annotations

from uuid import UUID

from app.domain.entities.event import Event
from app.domain.repositories.event_repository import (
    EventRepository,
)
from app.domain.repositories.job_repository import (
    JobRepository,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId


class GetJobHistoryService:
    """
    Returns the complete event history
    for a job aggregate.

    Events carry no tenant yet, so the job is looked up in the
    caller's tenant first. A job in another tenant, a missing
    job and an id that is not a UUID all return an empty
    history, so a caller cannot tell them apart (ADR 0064,
    point 5).
    """

    def __init__(
        self,
        job_repository: JobRepository,
        event_repository: EventRepository,
    ) -> None:
        self._job_repository = job_repository
        self._event_repository = event_repository

    def execute(
        self,
        aggregate_id: str,
        tenant_id: TenantId,
    ) -> list[Event]:
        """
        Return all events recorded for the supplied job, or an
        empty list if the job is not in the caller's tenant.
        """
        try:
            job_id = JobId(value=UUID(aggregate_id))
        except ValueError:
            return []

        if self._job_repository.get_by_id(job_id, tenant_id) is None:
            return []

        return self._event_repository.list_by_aggregate(
            aggregate_id,
        )
