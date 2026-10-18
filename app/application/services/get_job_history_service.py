from __future__ import annotations

from app.domain.entities.event import Event
from app.domain.repositories.event_repository import (
    EventRepository,
)
from app.domain.value_objects.tenant_id import TenantId


class GetJobHistoryService:
    """
    Returns the complete event history
    for a job aggregate.

    Events carry the tenant of their job (ADR 0074), so the read is
    made inside the caller's tenant. A job in another tenant, a
    missing job and an id that is not a UUID all return an empty
    history, so a caller cannot tell them apart (ADR 0064,
    point 5).
    """

    def __init__(
        self,
        event_repository: EventRepository,
    ) -> None:
        self._event_repository = event_repository

    def execute(
        self,
        aggregate_id: str,
        tenant_id: TenantId,
    ) -> list[Event]:
        """
        Return all events recorded for the supplied job in the
        caller's tenant, or an empty list.
        """
        return self._event_repository.list_by_aggregate(
            aggregate_id,
            tenant_id,
        )
