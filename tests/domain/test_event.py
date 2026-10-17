from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from app.domain.entities.event import Event
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.event_id import EventId


def test_create_domain_event() -> None:
    event = Event(
        id=EventId.new(),
        aggregate_id="job-123",
        aggregate_type="Job",
        tenant_id=DEFAULT_TENANT_ID,
        event_type="JobScheduled",
        occurred_at=datetime.now(UTC),
        payload={
            "node_id": "node-1",
        },
    )

    assert event.aggregate_id == "job-123"
    assert event.aggregate_type == "Job"
    assert event.event_type == "JobScheduled"
    assert event.payload == {
        "node_id": "node-1",
    }


def test_event_is_immutable() -> None:
    event = Event(
        id=EventId.new(),
        aggregate_id="job-123",
        aggregate_type="Job",
        tenant_id=DEFAULT_TENANT_ID,
        event_type="JobQueued",
        payload={},
    )

    with pytest.raises(FrozenInstanceError):
        event.event_type = "JobCompleted"


def test_an_event_requires_a_tenant() -> None:
    with pytest.raises(TypeError):
        Event(
            id=EventId.new(),
            aggregate_id="job-123",
            aggregate_type="Job",
            event_type="JobQueued",
        )
