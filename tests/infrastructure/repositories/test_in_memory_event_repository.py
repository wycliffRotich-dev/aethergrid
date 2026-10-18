from datetime import UTC, datetime

from app.domain.entities.event import Event
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.event_id import EventId
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)


def test_save_and_list_events() -> None:
    repository = InMemoryEventRepository()

    event = Event(
        id=EventId.new(),
        aggregate_id="job-1",
        aggregate_type="Job",
        tenant_id=DEFAULT_TENANT_ID,
        event_type="JobQueued",
        occurred_at=datetime.now(UTC),
        payload={
            "priority": "10",
        },
    )

    repository.save(
        event,
    )

    events = repository.list(DEFAULT_TENANT_ID)

    assert events == [
        event,
    ]


def test_list_events_by_aggregate() -> None:
    repository = InMemoryEventRepository()

    event_1 = Event(
        id=EventId.new(),
        aggregate_id="job-1",
        aggregate_type="Job",
        tenant_id=DEFAULT_TENANT_ID,
        event_type="JobQueued",
        payload={},
    )

    event_2 = Event(
        id=EventId.new(),
        aggregate_id="job-2",
        aggregate_type="Job",
        tenant_id=DEFAULT_TENANT_ID,
        event_type="JobQueued",
        payload={},
    )

    repository.save(
        event_1,
    )

    repository.save(
        event_2,
    )

    assert repository.list_by_aggregate(
        "job-1",
        DEFAULT_TENANT_ID,
    ) == [
        event_1,
    ]
