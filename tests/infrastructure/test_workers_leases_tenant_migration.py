"""ADR 0075, slice 1: migration 0004 gives workers and leases a tenant."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from app.infrastructure.migrations.runner import MigrationError
from tests.infrastructure.test_baseline_migration import Db


@pytest.fixture
def db(test_database_url: str) -> Iterator[Db]:
    schema = f"workers_tenant_{uuid.uuid4().hex[:12]}"
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


_TENANT_OF = {
    "workers": "SELECT tenant_id::text FROM workers WHERE id = %s",
    "leases": "SELECT tenant_id::text FROM leases WHERE id = %s",
}


def _tenant(db: Db, name: str) -> str:
    tenant_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO tenants (id, name, created_at) VALUES (%s, %s, now())",
        (tenant_id, name),
    )
    return tenant_id


def _node(db: Db, tenant_id: str) -> str:
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


def _worker_without_tenant(
    db: Db, node_id: str, running_job_id: str | None = None
) -> str:
    """What an image from before this change writes."""
    worker_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO workers (id, node_id, status, running_job_id, "
        "last_seen_at) VALUES (%s, %s, 'IDLE', %s, now())",
        (worker_id, node_id, running_job_id),
    )
    return worker_id


def _worker(
    db: Db, tenant_id: str, node_id: str, running_job_id: str | None = None
) -> str:
    worker_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO workers (id, node_id, status, running_job_id, "
        "last_seen_at, tenant_id) VALUES (%s, %s, 'IDLE', %s, now(), %s)",
        (worker_id, node_id, running_job_id, tenant_id),
    )
    return worker_id


def _lease_without_tenant(db: Db, worker_id: str, job_id: str) -> str:
    """What an image from before this change writes."""
    lease_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO leases (id, worker_id, job_id, acquired_at, expires_at) "
        "VALUES (%s, %s, %s, now(), now() + interval '30 seconds')",
        (lease_id, worker_id, job_id),
    )
    return lease_id


def _lease(db: Db, tenant_id: str, worker_id: str, job_id: str) -> str:
    lease_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO leases (id, worker_id, job_id, acquired_at, expires_at, "
        "tenant_id) VALUES (%s, %s, %s, now(), "
        "now() + interval '30 seconds', %s)",
        (lease_id, worker_id, job_id, tenant_id),
    )
    return lease_id


def _tenant_of(db: Db, table: str, row_id: str) -> str | None:
    row = db.conn.execute(_TENANT_OF[table], (row_id,)).fetchone()
    assert row is not None
    return row[0]


def _has_column(db: Db, table: str) -> bool:
    row = db.conn.execute(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s "
        "AND column_name = 'tenant_id'",
        (table,),
    ).fetchone()
    assert row is not None
    return row[0] == 1


def _applied(db: Db, version: int) -> bool:
    row = db.conn.execute(
        "SELECT count(*) FROM schema_migrations WHERE version = %s",
        (version,),
    ).fetchone()
    assert row is not None
    return row[0] == 1


def _upgrade(db: Db) -> None:
    db.run_up_to(3)
    assert db.run_up_to(4) == [4]


def test_a_worker_takes_its_nodes_tenant_and_a_lease_takes_its_workers(
    db: Db,
) -> None:
    db.run_up_to(3)
    tenant_a = _tenant(db, "a")
    tenant_b = _tenant(db, "b")
    node_a = _node(db, tenant_a)
    node_b = _node(db, tenant_b)
    job_a = _job(db, tenant_a)
    busy_a = _worker_without_tenant(db, node_a, running_job_id=job_a)
    idle_b = _worker_without_tenant(db, node_b)
    lease_a = _lease_without_tenant(db, busy_a, job_a)

    assert db.run_up_to(4) == [4]

    assert _tenant_of(db, "workers", busy_a) == tenant_a
    assert _tenant_of(db, "workers", idle_b) == tenant_b
    assert _tenant_of(db, "leases", lease_a) == tenant_a


def test_the_database_refuses_a_worker_in_another_tenant_than_its_node(
    db: Db,
) -> None:
    _upgrade(db)
    tenant_a = _tenant(db, "a")
    tenant_b = _tenant(db, "b")
    node_a = _node(db, tenant_a)

    with pytest.raises(psycopg.errors.ForeignKeyViolation) as refused:
        _worker(db, tenant_b, node_a)

    assert refused.value.diag.constraint_name == "workers_node_same_tenant"


def test_the_database_refuses_a_worker_running_another_tenants_job(
    db: Db,
) -> None:
    _upgrade(db)
    tenant_a = _tenant(db, "a")
    tenant_b = _tenant(db, "b")
    node_a = _node(db, tenant_a)
    job_b = _job(db, tenant_b)

    with pytest.raises(psycopg.errors.ForeignKeyViolation) as refused:
        _worker(db, tenant_a, node_a, running_job_id=job_b)

    assert refused.value.diag.constraint_name == "workers_running_job_same_tenant"


def test_the_database_refuses_a_lease_whose_worker_is_in_another_tenant(
    db: Db,
) -> None:
    _upgrade(db)
    tenant_a = _tenant(db, "a")
    tenant_b = _tenant(db, "b")
    worker_a = _worker(db, tenant_a, _node(db, tenant_a))
    job_b = _job(db, tenant_b)

    with pytest.raises(psycopg.errors.ForeignKeyViolation) as refused:
        _lease(db, tenant_b, worker_a, job_b)

    assert refused.value.diag.constraint_name == "leases_worker_same_tenant"


def test_the_database_refuses_a_lease_whose_job_is_in_another_tenant(
    db: Db,
) -> None:
    _upgrade(db)
    tenant_a = _tenant(db, "a")
    tenant_b = _tenant(db, "b")
    worker_a = _worker(db, tenant_a, _node(db, tenant_a))
    job_b = _job(db, tenant_b)

    with pytest.raises(psycopg.errors.ForeignKeyViolation) as refused:
        _lease(db, tenant_a, worker_a, job_b)

    assert refused.value.diag.constraint_name == "leases_job_same_tenant"


def test_deleting_a_running_job_clears_the_link_and_keeps_the_tenant(
    db: Db,
) -> None:
    _upgrade(db)
    # The single column key also clears the link, so with it in place this
    # test would pass even if the composite key nulled the tenant as well.
    # It is dropped here, in a scratch schema, to isolate the composite key
    # (ADR 0064, consequences). 0005 drops it for real.
    db.conn.execute(
        "ALTER TABLE workers DROP CONSTRAINT workers_running_job_id_fkey"
    )
    tenant_a = _tenant(db, "a")
    node_a = _node(db, tenant_a)
    job_a = _job(db, tenant_a)
    worker = _worker(db, tenant_a, node_a, running_job_id=job_a)

    db.conn.execute("DELETE FROM jobs WHERE id = %s", (job_a,))

    row = db.conn.execute(
        "SELECT running_job_id::text, tenant_id::text FROM workers "
        "WHERE id = %s",
        (worker,),
    ).fetchone()
    assert row == (None, tenant_a)


def test_an_older_image_can_still_write_workers_and_leases_with_no_tenant(
    db: Db,
) -> None:
    _upgrade(db)
    tenant_a = _tenant(db, "a")
    node_a = _node(db, tenant_a)
    job_a = _job(db, tenant_a)

    worker = _worker_without_tenant(db, node_a, running_job_id=job_a)
    lease = _lease_without_tenant(db, worker, job_a)

    assert _tenant_of(db, "workers", worker) is None
    assert _tenant_of(db, "leases", lease) is None


def test_a_worker_running_another_tenants_job_stops_the_migration(
    db: Db,
) -> None:
    db.run_up_to(3)
    tenant_a = _tenant(db, "a")
    tenant_b = _tenant(db, "b")
    node_a = _node(db, tenant_a)
    job_b = _job(db, tenant_b)
    crossing = _worker_without_tenant(db, node_a, running_job_id=job_b)

    with pytest.raises((MigrationError, psycopg.Error)) as refused:
        db.run_up_to(4)

    text = f"{refused.value} {refused.value.__cause__}"
    assert "workers_running_job_same_tenant" in text
    assert not _has_column(db, "workers")
    assert not _has_column(db, "leases")
    assert not _applied(db, 4)
    assert db.conn.execute(
        "SELECT count(*) FROM workers WHERE id = %s", (crossing,)
    ).fetchone() == (1,)
