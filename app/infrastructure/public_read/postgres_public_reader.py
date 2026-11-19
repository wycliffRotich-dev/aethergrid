"""
The Postgres reader of the five public views (ADR 0102, decision 2).

It implements the read port of the public demo and selects from the five
public views and from nothing else. Each query is a fixed string with a
named column list, a fixed order that ends with the id, and a bound limit.
Nothing is built from text and nothing writes. A test reads the source of
this package and refuses any other shape.

The limit is checked before the pool is used. A value that is not an integer
raises TypeError, a bool included, and an integer below one raises
ValueError. A larger limit is cut to MAX_LIMIT, which is read each time a
call is made.

The tenant is never an argument. The views show the one tenant named in the
scope table of the database (ADR 0098).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from psycopg.rows import class_row
from psycopg_pool import ConnectionPool

from app.application.public_read_port import (
    PublicEventRecord,
    PublicJobRecord,
    PublicLeaseRecord,
    PublicNodeRecord,
    PublicWorkerRecord,
)

MAX_LIMIT = 100

_Record = TypeVar("_Record")

_NODES = (
    "SELECT id, name, capacity_cpu_cores, capacity_memory_mib, "
    "capacity_vram_mib, available_cpu_cores, available_memory_mib, "
    "available_vram_mib, last_seen_at, draining "
    "FROM public_nodes "
    "ORDER BY name, id "
    "LIMIT %s"
)

_JOBS = (
    "SELECT id, cpu_cores, memory_mib, vram_mib, priority, max_retries, "
    "retry_count, status, assigned_node_id, submitted_at, started_at, "
    "completed_at, execution_timeout_seconds "
    "FROM public_jobs "
    "ORDER BY submitted_at DESC, id "
    "LIMIT %s"
)

_WORKERS = (
    "SELECT id, node_id, status, running_job_id, last_seen_at "
    "FROM public_workers "
    "ORDER BY last_seen_at DESC, id "
    "LIMIT %s"
)

_LEASES = (
    "SELECT id, worker_id, job_id, acquired_at, expires_at "
    "FROM public_leases "
    "ORDER BY expires_at, id "
    "LIMIT %s"
)

_EVENTS = (
    "SELECT id, aggregate_id, aggregate_type, event_type, occurred_at "
    "FROM public_events "
    "ORDER BY occurred_at DESC, id "
    "LIMIT %s"
)


def _bounded(limit: object) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")

    if limit < 1:
        raise ValueError("limit must be at least 1")

    return min(limit, MAX_LIMIT)


class PostgresPublicReader:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def list_nodes(self, limit: int) -> Sequence[PublicNodeRecord]:
        return self._read(_NODES, PublicNodeRecord, limit)

    def list_jobs(self, limit: int) -> Sequence[PublicJobRecord]:
        return self._read(_JOBS, PublicJobRecord, limit)

    def list_workers(self, limit: int) -> Sequence[PublicWorkerRecord]:
        return self._read(_WORKERS, PublicWorkerRecord, limit)

    def list_leases(self, limit: int) -> Sequence[PublicLeaseRecord]:
        return self._read(_LEASES, PublicLeaseRecord, limit)

    def list_events(self, limit: int) -> Sequence[PublicEventRecord]:
        return self._read(_EVENTS, PublicEventRecord, limit)

    def _read(
        self, query: str, record: type[_Record], limit: object
    ) -> list[_Record]:
        bound = _bounded(limit)

        with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=class_row(record)) as cursor,
        ):
            cursor.execute(query, (bound,))

            return cursor.fetchall()
