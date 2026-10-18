from __future__ import annotations

import json

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.domain.entities.event import Event
from app.domain.repositories.event_repository import (
    EventRepository,
)
from app.domain.value_objects.event_id import EventId
from app.domain.value_objects.tenant_id import TenantId


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
        Persist a domain event (ADR 0074).

        job_id is read from aggregate_id in the statement, so an
        aggregate_id that is not a UUID is refused here, and the
        composite key refuses an event whose job is missing or in
        another tenant. A repeated id changes nothing: an event is
        immutable, and an overwrite could move it to another tenant.
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
                    payload,
                    job_id,
                    tenant_id
                )
                VALUES (
                    %(id)s,
                    %(aggregate_id)s,
                    %(aggregate_type)s,
                    %(event_type)s,
                    %(occurred_at)s,
                    %(payload)s,
                    %(job_id)s::uuid,
                    %(tenant_id)s
                )
                ON CONFLICT (id) DO NOTHING
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
                    "job_id": event.aggregate_id,
                    "tenant_id": str(event.tenant_id),
                },
            )

    def list(
        self,
        tenant_id: TenantId,
    ) -> list[Event]:
        """
        Return the events of this tenant.

        An event an older image wrote without a tenant never equals
        a tenant, so it is shown to nobody (ADR 0074 decision 7).
        """

        with self._pool.connection() as conn:
            rows = conn.cursor(row_factory=dict_row).execute(
                """
                SELECT *
                FROM events
                WHERE tenant_id = %s
                ORDER BY occurred_at
                """,
                (
                    str(tenant_id),
                ),
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
        tenant_id: TenantId,
    ) -> list[Event]:
        """
        Return the events of one aggregate in this tenant (ADR 0074
        decisions 4 and 7).
        """

        with self._pool.connection() as conn:
            rows = conn.cursor(row_factory=dict_row).execute(
                """
                SELECT *
                FROM events
                WHERE aggregate_id = %s
                AND tenant_id = %s
                ORDER BY occurred_at
                """,
                (
                    aggregate_id,
                    str(tenant_id),
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
            tenant_id=TenantId(
                str(
                    row["tenant_id"],
                ),
            ),
            occurred_at=row["occurred_at"],
            payload=payload,
        )
