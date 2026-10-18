from sqlite3 import Connection

from app.domain.entities.event import Event
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.event_id import EventId
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.sqlite_connection import (
    create_connection,
)
from app.infrastructure.repositories.sqlite_event_repository import (
    SqliteEventRepository,
)


class TestSqliteEventRepositoryContract:
    """
    Contract tests for the SQLite EventRepository implementation.
    """

    connection: Connection

    def setup_method(self) -> None:
        self.connection = create_connection(
            ":memory:",
        )

        self.repository = SqliteEventRepository(
            self.connection,
        )

    def test_save_and_list_returns_saved_event(
        self,
    ) -> None:
        event = Event(
            id=EventId.new(),
            aggregate_id="job-123",
            aggregate_type="Job",
            tenant_id=DEFAULT_TENANT_ID,
            event_type="JobCreated",
        )

        self.repository.save(
            event,
        )

        events = self.repository.list(DEFAULT_TENANT_ID)

        assert len(events) == 1

        assert events[0].id == event.id
        assert events[0].aggregate_id == event.aggregate_id
        assert events[0].aggregate_type == event.aggregate_type
        assert events[0].event_type == event.event_type

    def test_list_by_aggregate_returns_only_matching_events(
        self,
    ) -> None:
        first = Event(
            id=EventId.new(),
            aggregate_id="job-1",
            aggregate_type="Job",
            tenant_id=DEFAULT_TENANT_ID,
            event_type="JobCreated",
        )

        second = Event(
            id=EventId.new(),
            aggregate_id="job-2",
            aggregate_type="Job",
            tenant_id=DEFAULT_TENANT_ID,
            event_type="JobCreated",
        )

        third = Event(
            id=EventId.new(),
            aggregate_id="job-1",
            aggregate_type="Job",
            tenant_id=DEFAULT_TENANT_ID,
            event_type="JobScheduled",
        )

        self.repository.save(
            first,
        )

        self.repository.save(
            second,
        )

        self.repository.save(
            third,
        )

        events = self.repository.list_by_aggregate(
            "job-1",
            DEFAULT_TENANT_ID,
        )

        assert len(events) == 2

        assert events[0].id == first.id
        assert events[1].id == third.id

    def test_the_tenant_round_trips(
        self,
    ) -> None:
        tenant_id = TenantId.new()
        event = Event(
            id=EventId.new(),
            aggregate_id="job-1",
            aggregate_type="Job",
            event_type="JobCreated",
            tenant_id=tenant_id,
        )

        self.repository.save(
            event,
        )

        assert self.repository.list(tenant_id)[0].tenant_id == tenant_id

    def test_an_events_table_from_before_tenancy_is_upgraded(
        self,
    ) -> None:
        connection = create_connection(
            ":memory:",
        )
        connection.execute(
            """
            CREATE TABLE events (
                id TEXT PRIMARY KEY,
                aggregate_id TEXT NOT NULL,
                aggregate_type TEXT NOT NULL,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(EventId.new()),
                "job-old",
                "Job",
                "JobCreated",
                "2026-01-01T00:00:00+00:00",
                "{}",
            ),
        )
        connection.commit()

        repository = SqliteEventRepository(
            connection,
        )

        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(events)",
            )
        }
        assert "tenant_id" in columns
        assert repository.list(DEFAULT_TENANT_ID) == []
        assert repository.list_by_aggregate("job-old", DEFAULT_TENANT_ID) == []

        event = Event(
            id=EventId.new(),
            aggregate_id="job-new",
            aggregate_type="Job",
            event_type="JobCreated",
            tenant_id=DEFAULT_TENANT_ID,
        )
        repository.save(
            event,
        )

        assert [e.id for e in repository.list(DEFAULT_TENANT_ID)] == [event.id]
