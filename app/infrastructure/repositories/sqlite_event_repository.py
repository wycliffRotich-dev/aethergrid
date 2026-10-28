from __future__ import annotations

import builtins
import json
from datetime import UTC, datetime
from sqlite3 import Connection

from app.domain.entities.event import Event
from app.domain.repositories.event_repository import (
    EventRepository,
)
from app.domain.value_objects.event_id import EventId
from app.domain.value_objects.tenant_id import TenantId


class SqliteEventRepository(EventRepository):
    """
    SQLite implementation of the EventRepository contract.
    """

    def __init__(
        self,
        connection: Connection,
    ) -> None:
        self._connection = connection

        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                aggregate_id TEXT NOT NULL,
                aggregate_type TEXT NOT NULL,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                tenant_id TEXT NOT NULL
            )
            """
        )

        self._upgrade_tenant_column()

        self._connection.commit()

    def _upgrade_tenant_column(self) -> None:
        """
        Add the tenant column to an events table that predates it
        (ADR 0074).

        The column stays nullable on an upgraded file, because SQLite
        cannot add a NOT NULL column without a default, and a default
        would file old events under the wrong tenant. Old events keep
        a null tenant and are shown to no tenant. Nothing here guesses
        a tenant for them.
        """
        columns = {
            row["name"]
            for row in self._connection.execute(
                "PRAGMA table_info(events)",
            )
        }

        if "tenant_id" not in columns:
            self._connection.execute(
                "ALTER TABLE events ADD COLUMN tenant_id TEXT",
            )

    def save(
        self,
        event: Event,
    ) -> None:
        """
        Persist an event.
        """

        self._connection.execute(
            """
            INSERT INTO events (
                id,
                aggregate_id,
                aggregate_type,
                event_type,
                occurred_at,
                payload,
                tenant_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(event.id),
                event.aggregate_id,
                event.aggregate_type,
                event.event_type,
                event.occurred_at.isoformat(),
                json.dumps(
                    event.payload,
                ),
                str(
                    event.tenant_id,
                ),
            ),
        )

        self._connection.commit()

    def list(
        self,
        tenant_id: TenantId,
    ) -> list[Event]:
        """
        Return the stored events of this tenant. An event with no
        tenant never equals one, so it is shown to nobody.
        """

        rows = self._connection.execute(
            """
            SELECT
                id,
                aggregate_id,
                aggregate_type,
                event_type,
                occurred_at,
                payload,
                tenant_id
            FROM events
            WHERE tenant_id = ?
            ORDER BY rowid
            """,
            (
                str(tenant_id),
            ),
        ).fetchall()

        return [
            Event(
                id=EventId(
                    row[0],
                ),
                aggregate_id=row[1],
                aggregate_type=row[2],
                event_type=row[3],
                occurred_at=datetime.fromisoformat(
                    row[4],
                ).astimezone(
                    UTC,
                ),
                payload=json.loads(
                    row[5],
                ),
                tenant_id=TenantId(
                    row[6],
                ),
            )
            for row in rows
        ]

    def list_by_aggregate(
        self,
        aggregate_id: str,
        tenant_id: TenantId,
    ) -> builtins.list[Event]:
        """
        Return every event belonging to one aggregate.
        """

        rows = self._connection.execute(
            """
            SELECT
                id,
                aggregate_id,
                aggregate_type,
                event_type,
                occurred_at,
                payload,
                tenant_id
            FROM events
            WHERE aggregate_id = ?
            AND tenant_id = ?
            ORDER BY rowid
            """,
            (
                aggregate_id,
                str(tenant_id),
            ),
        ).fetchall()

        return [
            Event(
                id=EventId(
                    row[0],
                ),
                aggregate_id=row[1],
                aggregate_type=row[2],
                event_type=row[3],
                occurred_at=datetime.fromisoformat(
                    row[4],
                ).astimezone(
                    UTC,
                ),
                payload=json.loads(
                    row[5],
                ),
                tenant_id=TenantId(
                    row[6],
                ),
            )
            for row in rows
        ]
