from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.infrastructure.migrations.runner import MigrationError
from tests.infrastructure.test_baseline_migration import Db


@pytest.fixture
def db(test_database_url: str) -> Iterator[Db]:
    schema = f"events_tenant_{uuid.uuid4().hex[:12]}"
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


def _job(db: Db, tenant_id: str) -> str:
    job_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO jobs (id, cpu_cores, memory_mib, status, submitted_at, "
        "tenant_id) VALUES (%s, 1, 512, 'QUEUED', now(), %s)",
        (job_id, tenant_id),
    )
    return job_id


def _event(db: Db, aggregate_id: str, event_type: str = "JobCreated") -> str:
    event_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO events (id, aggregate_id, aggregate_type, event_type, "
        "occurred_at) VALUES (%s, %s, 'Job', %s, now())",
        (event_id, aggregate_id, event_type),
    )
    return event_id


def _rows(db: Db) -> dict[str, tuple[Any, Any]]:
    rows = db.conn.execute(
        "SELECT id::text, job_id::text, tenant_id::text FROM events"
    ).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}


def test_each_event_takes_the_tenant_of_its_own_job(db: Db) -> None:
    db.run_up_to(1)
    tenant_a = _tenant(db, "a")
    tenant_b = _tenant(db, "b")
    job_a = _job(db, tenant_a)
    job_b = _job(db, tenant_b)
    job_default = _job(db, str(DEFAULT_TENANT_ID))
    event_a = _event(db, job_a)
    event_b = _event(db, job_b)
    event_default = _event(db, job_default)

    assert db.run_up_to(2) == [2]

    rows = _rows(db)
    assert rows[event_a] == (job_a, tenant_a)
    assert rows[event_b] == (job_b, tenant_b)
    assert rows[event_default] == (job_default, str(DEFAULT_TENANT_ID))


def test_an_event_with_no_job_stays_null_and_nothing_guesses_a_tenant(
    db: Db,
) -> None:
    db.run_up_to(1)
    orphan = _event(db, str(uuid.uuid4()))
    not_a_uuid = _event(db, "job-123")

    db.run_up_to(2)

    rows = _rows(db)
    assert rows[orphan] == (None, None)
    assert rows[not_a_uuid] == (None, None)


def test_the_database_refuses_an_event_in_another_tenants_job(db: Db) -> None:
    db.run_up_to(2)
    tenant_a = _tenant(db, "a")
    tenant_b = _tenant(db, "b")
    job_a = _job(db, tenant_a)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.conn.execute(
            "INSERT INTO events (id, aggregate_id, aggregate_type, event_type, "
            "occurred_at, job_id, tenant_id) "
            "VALUES (%s, %s, 'Job', 'JobCreated', now(), %s, %s)",
            (str(uuid.uuid4()), job_a, job_a, tenant_b),
        )


def test_the_database_refuses_a_job_without_a_tenant(db: Db) -> None:
    db.run_up_to(2)
    job = _job(db, str(DEFAULT_TENANT_ID))

    with pytest.raises(psycopg.errors.CheckViolation):
        db.conn.execute(
            "INSERT INTO events (id, aggregate_id, aggregate_type, event_type, "
            "occurred_at, job_id) VALUES (%s, %s, 'Job', 'JobCreated', now(), %s)",
            (str(uuid.uuid4()), job, job),
        )


def test_the_database_refuses_an_aggregate_id_that_names_another_job(
    db: Db,
) -> None:
    db.run_up_to(2)
    job = _job(db, str(DEFAULT_TENANT_ID))
    other = _job(db, str(DEFAULT_TENANT_ID))

    with pytest.raises(psycopg.errors.CheckViolation):
        db.conn.execute(
            "INSERT INTO events (id, aggregate_id, aggregate_type, event_type, "
            "occurred_at, job_id, tenant_id) "
            "VALUES (%s, %s, 'Job', 'JobCreated', now(), %s, %s)",
            (str(uuid.uuid4()), other, job, str(DEFAULT_TENANT_ID)),
        )


def test_an_older_image_can_still_write_an_event_with_no_tenant(db: Db) -> None:
    db.run_up_to(2)

    event = _event(db, "anything")

    assert _rows(db)[event] == (None, None)


def _is_nullable(db: Db, column: str) -> bool:
    row = db.conn.execute(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_schema = current_schema() "
        "AND table_name = 'events' AND column_name = %s",
        (column,),
    ).fetchone()
    assert row is not None
    return row[0] == "YES"


def _applied(db: Db, version: int) -> bool:
    row = db.conn.execute(
        "SELECT count(*) FROM schema_migrations WHERE version = %s",
        (version,),
    ).fetchone()
    assert row is not None
    return row[0] == 1


def test_an_event_an_older_image_wrote_gets_its_tenant_from_its_job(
    db: Db,
) -> None:
    db.run_up_to(2)
    tenant_a = _tenant(db, "a")
    job_a = _job(db, tenant_a)
    legacy = _event(db, job_a)

    assert _rows(db)[legacy] == (None, None)

    assert db.run_up_to(3) == [3]

    assert _rows(db)[legacy] == (job_a, tenant_a)
    assert not _is_nullable(db, "job_id")
    assert not _is_nullable(db, "tenant_id")


def test_the_database_refuses_an_event_with_no_job_and_no_tenant(
    db: Db,
) -> None:
    db.run_up_to(3)

    with pytest.raises(psycopg.errors.NotNullViolation):
        _event(db, str(uuid.uuid4()))


def test_an_event_with_no_job_stops_the_migration_and_changes_nothing(
    db: Db,
) -> None:
    db.run_up_to(2)
    tenant_a = _tenant(db, "a")
    job_a = _job(db, tenant_a)
    resolvable = _event(db, job_a)
    orphan = _event(db, str(uuid.uuid4()))

    with pytest.raises((MigrationError, psycopg.Error)) as refused:
        db.run_up_to(3)

    assert "no job" in f"{refused.value} {refused.value.__cause__}"
    assert _rows(db)[resolvable] == (None, None)
    assert _rows(db)[orphan] == (None, None)
    assert _is_nullable(db, "tenant_id")
    assert not _applied(db, 3)
