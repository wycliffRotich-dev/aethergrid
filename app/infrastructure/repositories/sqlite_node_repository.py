from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from uuid import UUID

from app.domain.entities.node import Node
from app.domain.repositories.node_repository import (
    NodeRepository,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    capacity_cpu_cores INTEGER NOT NULL,
    capacity_memory_mib INTEGER NOT NULL,
    capacity_vram_mib INTEGER NOT NULL,
    available_cpu_cores INTEGER NOT NULL,
    available_memory_mib INTEGER NOT NULL,
    available_vram_mib INTEGER NOT NULL,
    labels TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    draining INTEGER NOT NULL
);
"""


class SqliteNodeRepository(NodeRepository):
    """
    SQLite-backed implementation of the node repository.

    Reconstructs Node entities from persisted rows. Note
    that Node.available is computed by Node.__post_init__
    (always reset to equal capacity on construction), so
    it must be assigned directly after construction to
    restore the true persisted remaining capacity.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        self._connection = connection
        self._connection.execute(_CREATE_TABLE_SQL)
        self._connection.commit()

    def save(
        self,
        node: Node,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO nodes (
                id,
                name,
                capacity_cpu_cores,
                capacity_memory_mib,
                capacity_vram_mib,
                available_cpu_cores,
                available_memory_mib,
                available_vram_mib,
                labels,
                last_seen_at,
                draining
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                capacity_cpu_cores = excluded.capacity_cpu_cores,
                capacity_memory_mib = excluded.capacity_memory_mib,
                capacity_vram_mib = excluded.capacity_vram_mib,
                available_cpu_cores = excluded.available_cpu_cores,
                available_memory_mib = excluded.available_memory_mib,
                available_vram_mib = excluded.available_vram_mib,
                labels = excluded.labels,
                last_seen_at = excluded.last_seen_at,
                draining = excluded.draining
            """,
            (
                str(node.id),
                node.name,
                node.capacity.cpu_cores,
                node.capacity.memory_mib,
                node.capacity.vram_mib,
                node.available.cpu_cores,
                node.available.memory_mib,
                node.available.vram_mib,
                json.dumps(node.labels),
                node.last_seen_at.isoformat(),
                int(node.draining),
            ),
        )
        self._connection.commit()

    def list(
        self,
    ) -> list[Node]:
        rows = self._connection.execute(
            "SELECT * FROM nodes",
        ).fetchall()

        return [self._row_to_node(row) for row in rows]

    def list_available(
        self,
    ) -> list[Node]:
        """
        Return all healthy nodes.

        Resource suitability is determined by the
        Scheduler through Node.can_host(), so this
        repository only filters unhealthy nodes.
        """
        return [node for node in self.list() if node.is_alive() and not node.is_draining()]

    def get_by_id(
        self,
        node_id: NodeId,
    ) -> Node | None:
        row = self._connection.execute(
            "SELECT * FROM nodes WHERE id = ?",
            (str(node_id),),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_node(row)

    def delete(
        self,
        node_id: NodeId,
    ) -> None:
        self._connection.execute(
            "DELETE FROM nodes WHERE id = ?",
            (str(node_id),),
        )
        self._connection.commit()

    def _row_to_node(
        self,
        row: sqlite3.Row,
    ) -> Node:
        node = Node(
            id=NodeId(value=UUID(row["id"])),
            capacity=ResourceRequirements(
                cpu_cores=row["capacity_cpu_cores"],
                memory_mib=row["capacity_memory_mib"],
                vram_mib=row["capacity_vram_mib"],
            ),
            name=row["name"],
            labels=json.loads(row["labels"]),
            last_seen_at=datetime.fromisoformat(
                row["last_seen_at"],
            ),
            draining=bool(row["draining"]),
        )

        # available is init=False and gets reset to
        # capacity by __post_init__, so it must be
        # restored to its true persisted value here.
        node.available = ResourceRequirements(
            cpu_cores=row["available_cpu_cores"],
            memory_mib=row["available_memory_mib"],
            vram_mib=row["available_vram_mib"],
        )

        return node
