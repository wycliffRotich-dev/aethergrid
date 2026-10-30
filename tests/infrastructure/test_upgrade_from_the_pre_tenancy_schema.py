from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.infrastructure.migrations.runner import (
    MIGRATIONS_DIR,
    apply_migrations,
    load_migrations,
)

PRE_TENANCY = Path(__file__).resolve().parent / "schema_pre_tenancy.sql"
TENANT_TABLES = ("api_keys", "nodes", "jobs", "workers", "leases", "events")


@dataclass
class Scratch:
    url: str
    connect_kwargs: dict[str, Any]
    lock_key: int
    conn: psycopg.Connection

    def migrate(self, up_to: int | None = None) -> list[int]:
        migrations = load_migrations(MIGRATIONS_DIR)
        if up_to is not None:
            migrations = [m for m in migrations if m.version <= up_to]
        return apply_migrations(
            self.url,
            migrations,
            connect_kwargs=self.connect_kwargs,
            lock_key=self.lock_key,
            lock_timeout_seconds=10.0,
        )


@pytest.fixture
def scratch(test_database_url: str) -> Iterator[Scratch]:
    schema = f"upgrade_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(test_database_url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.execute(f'SET search_path TO "{schema}"')
        try:
            yield Scratch(
                url=test_database_url,
                connect_kwargs={"options": f"-c search_path={schema}"},
                lock_key=uuid.uuid4().int >> 66,
                conn=conn,
            )
        finally:
            conn.execute("SET search_path TO public")
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


def _insert_pre_tenancy_rows(conn: psycopg.Connection) -> dict[str, uuid.UUID]:
    names = ("node", "job", "worker", "lease", "event", "key")
    ids = {name: uuid.uuid4() for name in names}
    conn.execute(
        "INSERT INTO nodes (id, name, capacity_cpu_cores, capacity_memory_mib, "
        "capacity_vram_mib, available_cpu_cores, available_memory_mib, "
        "available_vram_mib, last_seen_at) "
        "VALUES (%s, 'node', 8, 16384, 0, 7, 15872, 0, now())",
        (ids["node"],),
    )
    conn.execute(
        "INSERT INTO jobs (id, cpu_cores, memory_mib, status, assigned_node_id, "
        "submitted_at) VALUES (%s, 1, 512, 'RUNNING', %s, now())",
        (ids["job"], ids["node"]),
    )
    conn.execute(
        "INSERT INTO workers (id, node_id, status, running_job_id, last_seen_at) "
        "VALUES (%s, %s, 'BUSY', %s, now())",
        (ids["worker"], ids["node"], ids["job"]),
    )
    conn.execute(
        "INSERT INTO leases (id, worker_id, job_id, acquired_at, expires_at) "
        "VALUES (%s, %s, %s, now(), now() + interval '30 seconds')",
        (ids["lease"], ids["worker"], ids["job"]),
    )
    conn.execute(
        "INSERT INTO events (id, aggregate_id, aggregate_type, event_type, "
        "occurred_at) VALUES (%s, %s, 'Job', 'JobStarted', now())",
        (ids["event"], str(ids["job"])),
    )
    conn.execute(
        "INSERT INTO api_keys (id, key_hash, label, created_at) "
        "VALUES (%s, 'hash', 'key', now())",
        (ids["key"],),
    )
    return ids


def test_a_pre_tenancy_database_upgrades_through_every_migration(
    scratch: Scratch,
) -> None:
    """
    ADR 0064, point 10. A database from before tenancy, with a row in
    each of the six tables, is taken through every migration by the
    real runner. Every row lands in the default tenant, every tenant
    column is required, and the links between the rows survive.
    """
    conn = scratch.conn
    conn.execute(PRE_TENANCY.read_text())
    ids = _insert_pre_tenancy_rows(conn)

    for table in TENANT_TABLES:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (1,), table

    latest = max(m.version for m in load_migrations(MIGRATIONS_DIR))

    assert scratch.migrate() == list(range(1, latest + 1))

    for table in TENANT_TABLES:
        rows = conn.execute(f"SELECT tenant_id::text FROM {table}").fetchall()
        assert rows == [(str(DEFAULT_TENANT_ID),)], f"{table} is not in the default tenant"

        nullable = conn.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s "
            "AND column_name = 'tenant_id'",
            (table,),
        ).fetchone()
        assert nullable == ("NO",), f"{table}.tenant_id is nullable"

    links = {
        "event job": conn.execute("SELECT job_id::text FROM events").fetchone(),
        "job node": conn.execute("SELECT assigned_node_id::text FROM jobs").fetchone(),
        "worker job": conn.execute("SELECT running_job_id::text FROM workers").fetchone(),
    }
    assert links == {
        "event job": (str(ids["job"]),),
        "job node": (str(ids["node"]),),
        "worker job": (str(ids["job"]),),
    }

    assert scratch.migrate() == []
