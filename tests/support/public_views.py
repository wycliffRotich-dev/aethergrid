"""
Helpers for tests of code that reads the public views (ADR 0098, ADR 0102).

They build the state those tests need in a scratch schema that already holds
migration 0007: two tenants, one of them named in public_demo_scope, rows in
the five base tables, and the grants the operator script will give the read
role. Every function takes the plain connection of the test, so nothing here
depends on a test module.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

ROLE = "aethergrid_public_read"
VIEWS_MIGRATION = 7
VIEWS = (
    "public_events",
    "public_jobs",
    "public_leases",
    "public_nodes",
    "public_workers",
)


@dataclass(frozen=True)
class Chain:
    """The ids of one node, job, worker, lease and event that belong together."""

    node: uuid.UUID
    job: uuid.UUID
    worker: uuid.UUID
    lease: uuid.UUID
    event: uuid.UUID

    @classmethod
    def random(cls) -> Chain:
        return cls(
            uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        )

    @classmethod
    def same(cls, chain_id: uuid.UUID) -> Chain:
        return cls(chain_id, chain_id, chain_id, chain_id, chain_id)

    def of(self, table: str) -> uuid.UUID:
        return {
            "nodes": self.node,
            "jobs": self.job,
            "workers": self.worker,
            "leases": self.lease,
            "events": self.event,
        }[table]


def current_schema(conn: psycopg.Connection[Any]) -> str:
    row = conn.execute("SELECT current_schema()").fetchone()
    assert row is not None
    return str(row[0])


def make_tenant(conn: psycopg.Connection[Any], name: str) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO tenants (id, name, created_at) VALUES (%s, %s, now())",
        (tenant_id, name),
    )
    return tenant_id


def set_scope(conn: psycopg.Connection[Any], tenant_id: uuid.UUID) -> None:
    conn.execute(
        "INSERT INTO public_demo_scope (tenant_id) VALUES (%s)", (tenant_id,)
    )


def allow_views(conn: psycopg.Connection[Any], schema: str) -> None:
    """Test only. This is what the operator script will do on the demo database."""
    conn.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO {ROLE}')
    for view in VIEWS:
        conn.execute(f"GRANT SELECT ON {view} TO {ROLE}")


def seed_chain(
    conn: psycopg.Connection[Any],
    tenant_id: uuid.UUID,
    *,
    ids: Chain | None = None,
    name: str | None = None,
    submitted_at: datetime | None = None,
    last_seen_at: datetime | None = None,
    expires_at: datetime | None = None,
    occurred_at: datetime | None = None,
) -> Chain:
    """
    One node, job, worker, lease and event for the tenant.

    Values that a view exposes differ from each other on purpose, for example
    capacity and available on a node, so a test that compares fields notices
    two columns that were swapped.
    """
    chain = Chain.random() if ids is None else ids
    now = datetime.now(UTC)
    submitted = now if submitted_at is None else submitted_at
    seen = now if last_seen_at is None else last_seen_at
    expires = now + timedelta(seconds=30) if expires_at is None else expires_at
    occurred = now if occurred_at is None else occurred_at

    conn.execute(
        "INSERT INTO nodes (id, name, capacity_cpu_cores, capacity_memory_mib, "
        "capacity_vram_mib, available_cpu_cores, available_memory_mib, "
        "available_vram_mib, last_seen_at, tenant_id) "
        "VALUES (%s, %s, 8, 16384, 2048, 4, 8192, 1024, %s, %s)",
        (chain.node, f"node-{chain.node}" if name is None else name, now, tenant_id),
    )
    conn.execute(
        "INSERT INTO jobs (id, cpu_cores, memory_mib, vram_mib, priority, "
        "max_retries, retry_count, status, assigned_node_id, submitted_at, "
        "started_at, execution_timeout_seconds, tenant_id) "
        "VALUES (%s, 1, 512, 128, 3, 4, 2, 'RUNNING', %s, %s, %s, 90.5, %s)",
        (
            chain.job,
            chain.node,
            submitted,
            submitted + timedelta(seconds=1),
            tenant_id,
        ),
    )
    conn.execute(
        "INSERT INTO workers (id, node_id, status, running_job_id, "
        "last_seen_at, tenant_id) VALUES (%s, %s, 'BUSY', %s, %s, %s)",
        (chain.worker, chain.node, chain.job, seen, tenant_id),
    )
    conn.execute(
        "INSERT INTO leases (id, worker_id, job_id, acquired_at, expires_at, "
        "tenant_id) VALUES (%s, %s, %s, %s, %s, %s)",
        (
            chain.lease,
            chain.worker,
            chain.job,
            expires - timedelta(seconds=30),
            expires,
            tenant_id,
        ),
    )
    conn.execute(
        "INSERT INTO events (id, job_id, aggregate_id, aggregate_type, "
        "event_type, occurred_at, tenant_id) "
        "VALUES (%s, %s, %s, 'job', 'JOB_STARTED', %s, %s)",
        (chain.event, chain.job, str(chain.job), occurred, tenant_id),
    )
    return chain
