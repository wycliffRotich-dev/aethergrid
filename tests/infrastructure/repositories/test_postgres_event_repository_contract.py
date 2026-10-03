from __future__ import annotations

import pytest
from psycopg_pool import ConnectionPool

from app.domain.entities.event import Event
from app.domain.value_objects.event_id import EventId
from app.infrastructure.repositories.postgres_event_repository import (
    PostgresEventRepository,
)


class TestPostgresEventRepositoryContract:
    """
    Contract tests for PostgresEventRepository.
    """

    @pytest.fixture(autouse=True, scope="class")
    @classmethod
    def _pool(cls, test_database_url):
        cls.pool = ConnectionPool(test_database_url, open=True)
        yield
        cls.pool.close()

    def setup_method(
        self,
    ) -> None:
        self.repository = PostgresEventRepository(
            self.pool,
        )

        with self.pool.connection() as conn:
            conn.execute(
                "TRUNCATE TABLE events",
            )

    def test_save_and_list_returns_saved_event(
        self,
    ) -> None:
        event = Event(
            id=EventId.new(),
            aggregate_id="job-123",
            aggregate_type="Job",
            event_type="JobCreated",
        )

        self.repository.save(
            event,
        )

        events = self.repository.list()

        assert len(events) == 1
        assert events[0] == event

    def test_list_by_aggregate_returns_only_matching_events(
        self,
    ) -> None:
        first = Event(
            id=EventId.new(),
            aggregate_id="job-1",
            aggregate_type="Job",
            event_type="JobCreated",
        )

        second = Event(
            id=EventId.new(),
            aggregate_id="job-2",
            aggregate_type="Job",
            event_type="JobCreated",
        )

        third = Event(
            id=EventId.new(),
            aggregate_id="job-1",
            aggregate_type="Job",
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
        )

        assert len(events) == 2
        assert events[0] == first
        assert events[1] == third
