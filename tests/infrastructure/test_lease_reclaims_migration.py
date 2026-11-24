"""ADR 0107: migration 0008 creates the table of reclaimed leases."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from tests.infrastructure.test_baseline_migration import Db
from tests.support.public_views import ROLE

TABLE = "lease_reclaims"

RECOVERED_BY = ["expired_lease", "offline_node", "worker_registered"]

PRIVILEGES = [
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
]

EXPECTED_COLUMNS = [
    ("id", "uuid", "NO"),
    ("tenant_id", "uuid", "NO"),
    ("lease_id", "uuid", "NO"),
    ("worker_id", "uuid", "NO"),
    ("job_id", "uuid", "NO"),
    ("lease_acquired_at", "timestamp with time zone", "NO"),
    ("lease_expires_at", "timestamp with time zone", "NO"),
    ("reclaimed_at", "timestamp with time zone", "NO"),
    ("recovered_by", "text", "NO"),
]

EXPECTED_FOREIGN_KEYS = [
    (
        "lease_reclaims_job_same_tenant",
        ["job_id", "tenant_id"],
        "jobs",
        ["id", "tenant_id"],
    ),
    (
        "lease_reclaims_tenant_fkey",
        ["tenant_id"],
        "tenants",
        ["id"],
    ),
]

_PRIMARY_KEY = """
SELECT ARRAY(
    SELECT a.attname
    FROM unnest(c.conkey) WITH ORDINALITY k(attnum, ord)
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
    ORDER BY k.ord
)
FROM pg_constraint c
WHERE c.conrelid = to_regclass(%s::text) AND c.contype = 'p'
"""

_FOREIGN_KEYS = """
SELECT c.conname,
       ARRAY(SELECT a.attname
             FROM unnest(c.conkey) WITH ORDINALITY k(attnum, ord)
             JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
             ORDER BY k.ord),
       c.confrelid::regclass::text,
       ARRAY(SELECT a.attname
             FROM unnest(c.confkey) WITH ORDINALITY k(attnum, ord)
             JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.attnum
             ORDER BY k.ord)
FROM pg_constraint c
WHERE c.contype = 'f' AND c.conrelid = to_regclass(%s::text)
ORDER BY c.conname
"""


@pytest.fixture
def db(test_database_url: str) -> Iterator[Db]:
    schema = f"lease_reclaims_{uuid.uuid4().hex[:12]}"
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


@pytest.fixture
def migrated(db: Db) -> Db:
    db.run_up_to(8)
    return db


def _tenant(db: Db) -> str:
    tenant_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO tenants (id, name, created_at) VALUES (%s, %s, now())",
        (tenant_id, f"tenant-{tenant_id}"),
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


def _record(
    db: Db,
    tenant_id: str,
    job_id: str,
    *,
    lease_id: str | None = None,
    recovered_by: str = "expired_lease",
) -> str:
    record_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO lease_reclaims (id, tenant_id, lease_id, worker_id, job_id, "
        "lease_acquired_at, lease_expires_at, reclaimed_at, recovered_by) "
        "VALUES (%s, %s, %s, %s, %s, now() - interval '31 seconds', "
        "now() - interval '1 second', now(), %s)",
        (
            record_id,
            tenant_id,
            lease_id or str(uuid.uuid4()),
            str(uuid.uuid4()),
            job_id,
            recovered_by,
        ),
    )
    return record_id


def _count(db: Db) -> int:
    row = db.conn.execute(f"SELECT count(*) FROM {TABLE}").fetchone()
    assert row is not None
    return int(row[0])


def _holds(db: Db, privilege: str) -> bool:
    row = db.conn.execute(
        "SELECT has_table_privilege(%s::name, %s::text, %s::text)",
        (ROLE, TABLE, privilege),
    ).fetchone()
    assert row is not None
    return bool(row[0])


def test_migration_0008_is_the_next_after_0007(db: Db) -> None:
    assert db.run_up_to(8) == [1, 2, 3, 4, 5, 6, 7, 8]


def test_the_table_has_exactly_these_columns(migrated: Db) -> None:
    rows = migrated.conn.execute(
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s "
        "ORDER BY ordinal_position",
        (TABLE,),
    ).fetchall()

    assert rows == EXPECTED_COLUMNS


def test_the_primary_key_is_the_record_id(migrated: Db) -> None:
    row = migrated.conn.execute(_PRIMARY_KEY, (TABLE,)).fetchone()

    assert row is not None
    assert list(row[0]) == ["id"]


def test_the_foreign_keys_are_the_job_in_its_tenant_and_the_tenant(
    migrated: Db,
) -> None:
    rows = migrated.conn.execute(_FOREIGN_KEYS, (TABLE,)).fetchall()
    found = [(name, list(cols), table, list(refs)) for name, cols, table, refs in rows]

    assert found == EXPECTED_FOREIGN_KEYS


@pytest.mark.parametrize("path", RECOVERED_BY)
def test_each_recovery_path_is_accepted(migrated: Db, path: str) -> None:
    tenant = _tenant(migrated)
    job = _job(migrated, tenant)

    _record(migrated, tenant, job, recovered_by=path)

    assert _count(migrated) == 1


def test_an_unknown_recovery_path_is_refused(migrated: Db) -> None:
    tenant = _tenant(migrated)
    job = _job(migrated, tenant)

    with pytest.raises(psycopg.errors.CheckViolation):
        _record(migrated, tenant, job, recovered_by="manual")

    assert _count(migrated) == 0


def test_a_record_for_a_missing_job_is_refused(migrated: Db) -> None:
    tenant = _tenant(migrated)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _record(migrated, tenant, str(uuid.uuid4()))

    assert _count(migrated) == 0


def test_a_record_for_a_job_in_another_tenant_is_refused(migrated: Db) -> None:
    tenant_a = _tenant(migrated)
    tenant_b = _tenant(migrated)
    job_of_b = _job(migrated, tenant_b)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _record(migrated, tenant_a, job_of_b)

    assert _count(migrated) == 0

    _record(migrated, tenant_b, job_of_b)

    assert _count(migrated) == 1


def test_a_second_record_for_the_same_lease_in_a_tenant_is_refused(
    migrated: Db,
) -> None:
    tenant = _tenant(migrated)
    first_job = _job(migrated, tenant)
    second_job = _job(migrated, tenant)
    lease_id = str(uuid.uuid4())

    _record(migrated, tenant, first_job, lease_id=lease_id)

    with pytest.raises(psycopg.errors.UniqueViolation):
        _record(migrated, tenant, second_job, lease_id=lease_id)

    assert _count(migrated) == 1


def test_a_job_that_is_reclaimed_twice_keeps_two_records(migrated: Db) -> None:
    tenant = _tenant(migrated)
    job = _job(migrated, tenant)

    _record(migrated, tenant, job)
    _record(migrated, tenant, job)

    assert _count(migrated) == 2


def test_the_same_lease_id_in_two_tenants_keeps_two_records(migrated: Db) -> None:
    tenant_a = _tenant(migrated)
    tenant_b = _tenant(migrated)
    lease_id = str(uuid.uuid4())

    _record(migrated, tenant_a, _job(migrated, tenant_a), lease_id=lease_id)
    _record(migrated, tenant_b, _job(migrated, tenant_b), lease_id=lease_id)

    assert _count(migrated) == 2


def test_deleting_a_job_deletes_its_records(migrated: Db) -> None:
    tenant = _tenant(migrated)
    job = _job(migrated, tenant)
    _record(migrated, tenant, job)

    migrated.conn.execute("DELETE FROM jobs WHERE id = %s", (job,))

    assert _count(migrated) == 0


@pytest.mark.parametrize("privilege", PRIVILEGES)
def test_the_public_read_role_holds_no_privilege_on_the_table(
    migrated: Db,
    privilege: str,
) -> None:
    assert not _holds(migrated, privilege)


def test_the_privilege_check_can_fail(migrated: Db) -> None:
    migrated.conn.execute(f"GRANT SELECT ON {TABLE} TO {ROLE}")

    assert _holds(migrated, "SELECT")
