from __future__ import annotations

import json

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.domain.entities.event import Event
from app.domain.repositories.event_repository import (
    EventRepository,
)
from app.domain.value_objects.event_id import EventId


class PostgresEventRepository(EventRepository):
    """
    PostgreSQL-backed implementation of EventRepository.
    """

    def __init__(
        self,
        pool: ConnectionPool,
    ) -> None:
        self._pool = pool

    def save(
        self,
        event: Event,
    ) -> None:
        """
        Persist a domain event.
        """

        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    id,
                    aggregate_id,
                    aggregate_type,
                    event_type,
                    occurred_at,
                    payload
                )
                VALUES (
                    %(id)s,
                    %(aggregate_id)s,
                    %(aggregate_type)s,
                    %(event_type)s,
                    %(occurred_at)s,
                    %(payload)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    aggregate_id = EXCLUDED.aggregate_id,
                    aggregate_type = EXCLUDED.aggregate_type,
                    event_type = EXCLUDED.event_type,
                    occurred_at = EXCLUDED.occurred_at,
                    payload = EXCLUDED.payload
                """,
                {
                    "id": str(event.id),
                    "aggregate_id": event.aggregate_id,
                    "aggregate_type": event.aggregate_type,
                    "event_type": event.event_type,
                    "occurred_at": event.occurred_at,
                    "payload": json.dumps(
                        event.payload,
                    ),
                },
            )

    def list(
        self,
    ) -> list[Event]:
        """
        Return every persisted event.
        """

        with self._pool.connection() as conn:
            rows = conn.cursor(row_factory=dict_row).execute(
                """
                SELECT *
                FROM events
                ORDER BY occurred_at
                """,
            ).fetchall()

        return [
            self._to_entity(
                row,
            )
            for row in rows
        ]

    def list_by_aggregate(
        self,
        aggregate_id: str,
    ) -> list[Event]:
        """
        Return every event belonging to one aggregate.
        """

        with self._pool.connection() as conn:
            rows = conn.cursor(row_factory=dict_row).execute(
                """
                SELECT *
                FROM events
                WHERE aggregate_id = %s
                ORDER BY occurred_at
                """,
                (
                    aggregate_id,
                ),
            ).fetchall()

        return [
            self._to_entity(
                row,
            )
            for row in rows
        ]

    @staticmethod
    def _to_entity(
        row: dict,
    ) -> Event:
        """
        Convert a database row into an Event.
        """

        payload = row["payload"]

        if isinstance(
            payload,
            str,
        ):
            payload = json.loads(
                payload,
            )

        return Event(
            id=EventId.from_string(
                str(
                    row["id"],
                ),
            ),
            aggregate_id=row["aggregate_id"],
            aggregate_type=row["aggregate_type"],
            event_type=row["event_type"],
            occurred_at=row["occurred_at"],
            payload=payload,
        )
