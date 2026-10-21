"""
ADR 0075, slice 2: migration 0005 makes the tenant of workers and leases
required and drops the single column keys the composite keys replace.

The refusal cannot fire on a schema that kept its constraints, because a
worker has a node with a tenant and a lease has a worker. The test that
proves it relaxes nodes.tenant_id in its own scratch schema to build a
row that no backfill can repair.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from app.infrastructure.migrations.runner import MigrationError
from tests.infrastructure.test_baseline_migration import Db

OLD_KEYS = {
    "workers": ["workers_node_id_fkey", "workers_running_job_id_fkey"],
    "leases": ["leases_worker_id_fkey", "leases_job_id_fkey"],
}
COMPOSITE_KEYS = {
    "workers": ["workers_node_same_tenant", "workers_running_job_same_tenant"],
    "leases": ["leases_worker_same_tenant", "leases_job_same_tenant"],
}
KEPT_UNIQUE = ["leases_job_id_key", "leases_worker_id_key"]


@pytest.fixture
def db(test_database_url: str) -> Iterator[Db]:
    schema = f"required_tenant_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(test_database_url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.execute(f'SET search_path TO "{schema}"')
        try:
            yield Db(
                url=test_database_url,
                connect_kwargs={"options": f"-c search_path={schema}"},
                lock_key=uuid.uuid4().int >> 66,
                conn=conn,
            )
        finally:
            conn.execute("SET search_path TO public")
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


def _tenant(db: Db, name: str) -> str:
    tenant_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO tenants (id, name, created_at) VALUES (%s, %s, now())",
        (tenant_id, name),
    )
    return tenant_id


def _node(db: Db, tenant_id: str | None) -> str:
    node_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO nodes (id, name, capacity_cpu_cores, capacity_memory_mib, "
        "capacity_vram_mib, available_cpu_cores, available_memory_mib, "
        "available_vram_mib, last_seen_at, tenant_id) "
        "VALUES (%s, 'node', 8, 16384, 0, 8, 16384, 0, now(), %s)",
        (node_id, tenant_id),
    )
    return node_id


def _job(db: Db, tenant_id: str) -> str:
    job_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO jobs (id, cpu_cores, memory_mib, status, submitted_at, "
        "tenant_id) VALUES (%s, 1, 512, 'QUEUED', now(), %s)",
        (job_id, tenant_id),
    )
    return job_id


def _worker_without_tenant(db: Db, node_id: str, running_job_id: str | None = None) -> str:
    """What an image from before slice 1 writes."""
    worker_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO workers (id, node_id, status, running_job_id, last_seen_at) "
        "VALUES (%s, %s, 'IDLE', %s, now())",
        (worker_id, node_id, running_job_id),
    )
    return worker_id


def _worker(db: Db, tenant_id: str, node_id: str, running_job_id: str | None = None) -> str:
    worker_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO workers (id, node_id, status, running_job_id, "
        "last_seen_at, tenant_id) VALUES (%s, %s, 'IDLE', %s, now(), %s)",
        (worker_id, node_id, running_job_id, tenant_id),
    )
    return worker_id


def _lease_without_tenant(db: Db, worker_id: str, job_id: str) -> str:
    lease_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO leases (id, worker_id, job_id, acquired_at, expires_at) "
        "VALUES (%s, %s, %s, now(), now() + interval '30 seconds')",
        (lease_id, worker_id, job_id),
    )
    return lease_id


def _tenant_of(db: Db, table: str, row_id: str) -> str | None:
    row = db.conn.execute(
        f"SELECT tenant_id::text FROM {table} WHERE id = %s", (row_id,)
    ).fetchone()
    assert row is not None
    return row[0]


def _nullable(db: Db, table: str) -> bool:
    row = db.conn.execute(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s "
        "AND column_name = 'tenant_id'",
        (table,),
    ).fetchone()
    assert row is not None
    return row[0] == "YES"


def _constraint_names(db: Db, table: str) -> set[str]:
    rows = db.conn.execute(
        "SELECT conname FROM pg_constraint WHERE conrelid = to_regclass(%s)",
        (table,),
    ).fetchall()
    return {row[0] for row in rows}


def _applied(db: Db, version: int) -> bool:
    row = db.conn.execute(
        "SELECT count(*) FROM schema_migrations WHERE version = %s", (version,)
    ).fetchone()
    assert row is not None
    return row[0] == 1


def test_the_tenant_becomes_required_on_workers_and_leases(db: Db) -> None:
    db.run_up_to(4)
    assert _nullable(db, "workers") and _nullable(db, "leases")

    assert db.run_up_to(5) == [5]

    assert not _nullable(db, "workers")
    assert not _nullable(db, "leases")


def test_the_backfill_repairs_rows_an_older_image_wrote_after_0004(db: Db) -> None:
    db.run_up_to(4)
    tenant_a = _tenant(db, "a")
    node_a = _node(db, tenant_a)
    job_a = _job(db, tenant_a)
    worker = _worker_without_tenant(db, node_a, running_job_id=job_a)
    lease = _lease_without_tenant(db, worker, job_a)

    assert db.run_up_to(5) == [5]

    assert _tenant_of(db, "workers", worker) == tenant_a
    assert _tenant_of(db, "leases", lease) == tenant_a


def test_the_single_column_keys_go_and_the_composite_keys_and_unique_keys_stay(
    db: Db,
) -> None:
    db.run_up_to(4)
    for table, names in OLD_KEYS.items():
        assert set(names) <= _constraint_names(db, table)

    db.run_up_to(5)

    for table, names in OLD_KEYS.items():
        assert not set(names) & _constraint_names(db, table)
    for table, names in COMPOSITE_KEYS.items():
        assert set(names) <= _constraint_names(db, table)
    assert set(KEPT_UNIQUE) <= _constraint_names(db, "leases")


def test_the_migration_stops_and_names_the_count_when_a_row_has_no_tenant(
    db: Db,
) -> None:
    db.run_up_to(4)
    # A node always has a tenant, so no backfill can leave a worker without
    # one. Relax the node in this scratch schema to build the row anyway.
    db.conn.execute("ALTER TABLE nodes ALTER COLUMN tenant_id DROP NOT NULL")
    tenant_a = _tenant(db, "a")
    node = _node(db, None)
    job = _job(db, tenant_a)
    worker = _worker_without_tenant(db, node)
    lease = _lease_without_tenant(db, worker, job)

    with pytest.raises((MigrationError, psycopg.Error)) as refused:
        db.run_up_to(5)

    message = f"{refused.value} {refused.value.__cause__}"
    assert "1 workers and 1 leases have no tenant" in message
    assert _tenant_of(db, "workers", worker) is None
    assert _tenant_of(db, "leases", lease) is None
    assert _nullable(db, "workers") and _nullable(db, "leases")
    assert set(OLD_KEYS["workers"]) <= _constraint_names(db, "workers")
    assert not _applied(db, 5)


def test_a_write_with_no_tenant_fails_after_0005(db: Db) -> None:
    db.run_up_to(5)
    tenant_a = _tenant(db, "a")
    node = _node(db, tenant_a)

    with pytest.raises(psycopg.errors.NotNullViolation):
        _worker_without_tenant(db, node)


def test_the_composite_keys_still_refuse_a_cross_tenant_worker(db: Db) -> None:
    db.run_up_to(5)
    tenant_a = _tenant(db, "a")
    tenant_b = _tenant(db, "b")
    node_a = _node(db, tenant_a)

    with pytest.raises(psycopg.errors.ForeignKeyViolation) as refused:
        _worker(db, tenant_b, node_a)

    assert refused.value.diag.constraint_name == "workers_node_same_tenant"


def test_the_composite_keys_still_refuse_a_worker_running_another_tenants_job(
    db: Db,
) -> None:
    db.run_up_to(5)
    tenant_a = _tenant(db, "a")
    tenant_b = _tenant(db, "b")
    node_a = _node(db, tenant_a)
    job_b = _job(db, tenant_b)

    with pytest.raises(psycopg.errors.ForeignKeyViolation) as refused:
        _worker(db, tenant_a, node_a, running_job_id=job_b)

    assert refused.value.diag.constraint_name == "workers_running_job_same_tenant"


def test_deleting_a_running_job_clears_the_link_and_keeps_the_tenant(db: Db) -> None:
    db.run_up_to(5)
    tenant_a = _tenant(db, "a")
    node = _node(db, tenant_a)
    job = _job(db, tenant_a)
    worker = _worker(db, tenant_a, node, running_job_id=job)

    db.conn.execute("DELETE FROM jobs WHERE id = %s", (job,))

    row = db.conn.execute(
        "SELECT running_job_id, tenant_id::text FROM workers WHERE id = %s", (worker,)
    ).fetchone()
    assert row == (None, tenant_a)


def test_a_lease_write_with_no_tenant_fails_after_0005(db: Db) -> None:
    db.run_up_to(5)
    tenant_a = _tenant(db, "a")
    node = _node(db, tenant_a)
    job = _job(db, tenant_a)
    worker = _worker(db, tenant_a, node)

    with pytest.raises(psycopg.errors.NotNullViolation):
        _lease_without_tenant(db, worker, job)


def test_a_worker_cannot_have_its_tenant_removed_after_0005(db: Db) -> None:
    db.run_up_to(5)
    tenant_a = _tenant(db, "a")
    worker = _worker(db, tenant_a, _node(db, tenant_a))

    with pytest.raises(psycopg.errors.NotNullViolation):
        db.conn.execute("UPDATE workers SET tenant_id = NULL WHERE id = %s", (worker,))

    assert _tenant_of(db, "workers", worker) == tenant_a


def test_a_lease_cannot_have_its_tenant_removed_after_0005(db: Db) -> None:
    db.run_up_to(5)
    tenant_a = _tenant(db, "a")
    job = _job(db, tenant_a)
    worker = _worker(db, tenant_a, _node(db, tenant_a))
    lease = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO leases (id, worker_id, job_id, acquired_at, expires_at, tenant_id) "
        "VALUES (%s, %s, %s, now(), now() + interval '30 seconds', %s)",
        (lease, worker, job, tenant_a),
    )

    with pytest.raises(psycopg.errors.NotNullViolation):
        db.conn.execute("UPDATE leases SET tenant_id = NULL WHERE id = %s", (lease,))

    assert _tenant_of(db, "leases", lease) == tenant_a
