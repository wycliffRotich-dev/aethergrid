from __future__ import annotations

from app.domain.entities.event import Event
from app.domain.repositories.event_repository import (
    EventRepository,
)
from app.domain.value_objects.tenant_id import TenantId


class InMemoryEventRepository(EventRepository):
    """
    In-memory implementation of the EventRepository.
    """

    def __init__(self) -> None:
        self._events: list[Event] = []

    def save(
        self,
        event: Event,
    ) -> None:
        self._events.append(event)

    def list(
        self,
        tenant_id: TenantId,
    ) -> list[Event]:
        return [
            event
            for event in self._events
            if event.tenant_id == tenant_id
        ]

    def list_by_aggregate(
        self,
        aggregate_id: str,
        tenant_id: TenantId,
    ) -> list[Event]:
        return [
            event
            for event in self._events
            if event.aggregate_id == aggregate_id
            and event.tenant_id == tenant_id
        ]
