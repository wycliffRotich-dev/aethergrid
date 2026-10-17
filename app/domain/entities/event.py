from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.value_objects.event_id import EventId
from app.domain.value_objects.tenant_id import TenantId


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(
    frozen=True,
    slots=True,
)
class Event:
    """
    Immutable record describing a domain event.
    """

    id: EventId
    aggregate_id: str
    aggregate_type: str
    event_type: str
    tenant_id: TenantId
    """
    The tenant of the job this event is about (ADR 0074). Required,
    and read from the job when the event is recorded, never chosen
    by the writer.
    """
    occurred_at: datetime = field(
        default_factory=utc_now,
    )
    payload: dict[str, str] = field(
        default_factory=dict,
    )
