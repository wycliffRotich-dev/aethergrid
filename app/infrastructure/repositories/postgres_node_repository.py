from __future__ import annotations

import json

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.domain.entities.node import Node
from app.domain.repositories.node_repository import NodeRepository
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)


class PostgresNodeRepository(NodeRepository):
    """
    PostgreSQL-backed implementation of NodeRepository.

    Uses raw psycopg (no ORM) so that every query is
    explicit and the domain/infrastructure boundary stays
    unambiguous -- consistent with the rest of NeuroMesh's
    architecture.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def save(self, node: Node) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO nodes (
                    id, name, capacity_cpu_cores, capacity_memory_mib,
                    capacity_vram_mib, available_cpu_cores,
                    available_memory_mib, available_vram_mib,
                    labels, last_seen_at, draining
                ) VALUES (
                    %(id)s, %(name)s, %(capacity_cpu_cores)s, %(capacity_memory_mib)s,
                    %(capacity_vram_mib)s, %(available_cpu_cores)s,
                    %(available_memory_mib)s, %(available_vram_mib)s,
                    %(labels)s, %(last_seen_at)s, %(draining)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    capacity_cpu_cores = EXCLUDED.capacity_cpu_cores,
                    capacity_memory_mib = EXCLUDED.capacity_memory_mib,
                    capacity_vram_mib = EXCLUDED.capacity_vram_mib,
                    available_cpu_cores = EXCLUDED.available_cpu_cores,
                    available_memory_mib = EXCLUDED.available_memory_mib,
                    available_vram_mib = EXCLUDED.available_vram_mib,
                    labels = EXCLUDED.labels,
                    last_seen_at = EXCLUDED.last_seen_at,
                    draining = EXCLUDED.draining
                """,
                {
                    "id": str(node.id),
                    "name": node.name,
                    "capacity_cpu_cores": node.capacity.cpu_cores,
                    "capacity_memory_mib": node.capacity.memory_mib,
                    "capacity_vram_mib": node.capacity.vram_mib,
                    "available_cpu_cores": node.available.cpu_cores,
                    "available_memory_mib": node.available.memory_mib,
                    "available_vram_mib": node.available.vram_mib,
                    "labels": json.dumps(node.labels),
                    "last_seen_at": node.last_seen_at,
                    "draining": node.draining,
                },
            )

    def list(self) -> list[Node]:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute("SELECT * FROM nodes").fetchall()
        return [self._to_entity(row) for row in rows]

    def list_available(self) -> list[Node]:
        """
        Returns non-draining nodes.

        NOTE: this mirrors ADR 0003's stated direction that
        "available" is a domain concept -- but the exact
        definition (draining check only, vs. also requiring
        is_alive()) should be confirmed against how the
        scheduler actually calls this today.
        """
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute("SELECT * FROM nodes WHERE draining = false").fetchall()
        return [self._to_entity(row) for row in rows]

    def get_by_id(self, node_id: NodeId) -> Node | None:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                "SELECT * FROM nodes WHERE id = %s",
                (str(node_id),),
            ).fetchone()
        return self._to_entity(row) if row else None

    def delete(self, node_id: NodeId) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "DELETE FROM nodes WHERE id = %s",
                (str(node_id),),
            )

    @staticmethod
    def _to_entity(row: dict) -> Node:
        capacity = ResourceRequirements(
            cpu_cores=row["capacity_cpu_cores"],
            memory_mib=row["capacity_memory_mib"],
            vram_mib=row["capacity_vram_mib"],
        )
        available = ResourceRequirements(
            cpu_cores=row["available_cpu_cores"],
            memory_mib=row["available_memory_mib"],
            vram_mib=row["available_vram_mib"],
        )
        return Node(
            id=NodeId.from_string(str(row["id"])),
            capacity=capacity,
            available=available,
            name=row["name"],
            labels=row["labels"] or {},
            last_seen_at=row["last_seen_at"],
            draining=row["draining"],
        )
