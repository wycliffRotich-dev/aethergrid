"""ADR 0108: migration 0009 creates the table of refused lease calls."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from tests.infrastructure.test_baseline_migration import Db
from tests.support.public_views import ROLE

TABLE = "lease_refusals"

OPERATIONS = ["renew", "release"]
REASONS = ["no_active_lease", "lease_not_current"]

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
    ("operation", "text", "NO"),
    ("reason", "text", "NO"),
    ("refused_at", "timestamp with time zone", "NO"),
]

EXPECTED_FOREIGN_KEYS = [
    (
        "lease_refusals_job_same_tenant",
        ["job_id", "tenant_id"],
        "jobs",
        ["id", "tenant_id"],
    ),
    (
        "lease_refusals_reclaim_same_tenant",
        ["tenant_id", "lease_id"],
        "lease_reclaims",
        ["tenant_id", "lease_id"],
    ),
]

_COLUMNS = """
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = current_schema() AND table_name = %s
ORDER BY ordinal_position
"""

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
    schema = f"lease_refusals_{uuid.uuid4().hex[:12]}"
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
    db.run_up_to(9)
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


def _reclaim(
    db: Db,
    tenant_id: str,
    job_id: str,
    lease_id: str | None = None,
) -> str:
    lease_id = lease_id or str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO lease_reclaims (id, tenant_id, lease_id, worker_id, job_id, "
        "lease_acquired_at, lease_expires_at, reclaimed_at, recovered_by) "
        "VALUES (%s, %s, %s, %s, %s, now() - interval '31 seconds', "
        "now() - interval '1 second', now(), 'expired_lease')",
        (str(uuid.uuid4()), tenant_id, lease_id, str(uuid.uuid4()), job_id),
    )
    return lease_id


def _refusal(
    db: Db,
    tenant_id: str,
    lease_id: str,
    job_id: str,
    *,
    operation: str = "renew",
    reason: str = "no_active_lease",
) -> str:
    refusal_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO lease_refusals (id, tenant_id, lease_id, worker_id, job_id, "
        "operation, reason, refused_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, now())",
        (
            refusal_id,
            tenant_id,
            lease_id,
            str(uuid.uuid4()),
            job_id,
            operation,
            reason,
        ),
    )
    return refusal_id


def _held(db: Db) -> tuple[str, str, str]:
    """A tenant, a job in it and the record of a lease reclaimed for it."""
    tenant_id = _tenant(db)
    job_id = _job(db, tenant_id)
    return tenant_id, job_id, _reclaim(db, tenant_id, job_id)


def _count(db: Db) -> int:
    row = db.conn.execute(f"SELECT count(*) FROM {TABLE}").fetchone()
    assert row is not None
    return int(row[0])


def test_the_table_has_the_columns_of_the_record(migrated: Db) -> None:
    rows = migrated.conn.execute(_COLUMNS, (TABLE,)).fetchall()

    assert [(name, kind, nullable) for name, kind, nullable in rows] == (
        EXPECTED_COLUMNS
    )


def test_the_primary_key_is_the_id(migrated: Db) -> None:
    row = migrated.conn.execute(_PRIMARY_KEY, (TABLE,)).fetchone()

    assert row is not None
    assert row[0] == ["id"]


def test_the_table_has_exactly_the_two_foreign_keys(migrated: Db) -> None:
    rows = migrated.conn.execute(_FOREIGN_KEYS, (TABLE,)).fetchall()

    assert [tuple(row) for row in rows] == [
        tuple(expected) for expected in EXPECTED_FOREIGN_KEYS
    ]


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("reason", REASONS)
def test_every_operation_and_reason_is_accepted(
    migrated: Db,
    operation: str,
    reason: str,
) -> None:
    tenant_id, job_id, lease_id = _held(migrated)

    _refusal(
        migrated,
        tenant_id,
        lease_id,
        job_id,
        operation=operation,
        reason=reason,
    )

    assert _count(migrated) == 1


def test_an_unknown_operation_is_refused(migrated: Db) -> None:
    tenant_id, job_id, lease_id = _held(migrated)

    with pytest.raises(psycopg.errors.CheckViolation):
        _refusal(migrated, tenant_id, lease_id, job_id, operation="cancel")

    assert _count(migrated) == 0


def test_an_unknown_reason_is_refused(migrated: Db) -> None:
    tenant_id, job_id, lease_id = _held(migrated)

    with pytest.raises(psycopg.errors.CheckViolation):
        _refusal(migrated, tenant_id, lease_id, job_id, reason="because")

    assert _count(migrated) == 0


def test_a_refusal_for_a_lease_that_reclaim_never_removed_is_refused(
    migrated: Db,
) -> None:
    tenant_id = _tenant(migrated)
    job_id = _job(migrated, tenant_id)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _refusal(migrated, tenant_id, str(uuid.uuid4()), job_id)

    assert _count(migrated) == 0


def test_a_refusal_in_another_tenant_than_the_reclaim_is_refused(
    migrated: Db,
) -> None:
    _tenant_a, _job_a, lease_id = _held(migrated)
    tenant_b = _tenant(migrated)
    job_b = _job(migrated, tenant_b)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _refusal(migrated, tenant_b, lease_id, job_b)

    assert _count(migrated) == 0


def test_a_refusal_for_a_job_in_another_tenant_is_refused(
    migrated: Db,
) -> None:
    tenant_a, _job_a, lease_id = _held(migrated)
    job_b = _job(migrated, _tenant(migrated))

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _refusal(migrated, tenant_a, lease_id, job_b)

    assert _count(migrated) == 0


def test_a_second_refusal_of_the_same_kind_is_refused(migrated: Db) -> None:
    tenant_id, job_id, lease_id = _held(migrated)
    _refusal(migrated, tenant_id, lease_id, job_id)

    with pytest.raises(psycopg.errors.UniqueViolation):
        _refusal(migrated, tenant_id, lease_id, job_id)

    assert _count(migrated) == 1


def test_another_operation_or_reason_of_the_same_lease_is_kept(
    migrated: Db,
) -> None:
    tenant_id, job_id, lease_id = _held(migrated)

    _refusal(migrated, tenant_id, lease_id, job_id)
    _refusal(migrated, tenant_id, lease_id, job_id, operation="release")
    _refusal(
        migrated,
        tenant_id,
        lease_id,
        job_id,
        reason="lease_not_current",
    )

    assert _count(migrated) == 3


def test_a_refusal_goes_when_its_reclaim_record_goes(migrated: Db) -> None:
    tenant_id, job_id, lease_id = _held(migrated)
    _refusal(migrated, tenant_id, lease_id, job_id)

    migrated.conn.execute(
        "DELETE FROM lease_reclaims WHERE tenant_id = %s AND lease_id = %s",
        (tenant_id, lease_id),
    )

    assert _count(migrated) == 0


def test_a_refusal_goes_when_its_job_goes(migrated: Db) -> None:
    tenant_id, job_id, lease_id = _held(migrated)
    _refusal(migrated, tenant_id, lease_id, job_id)

    migrated.conn.execute("DELETE FROM jobs WHERE id = %s", (job_id,))

    assert _count(migrated) == 0


@pytest.mark.parametrize("privilege", PRIVILEGES)
def test_the_public_read_role_holds_no_privilege_on_the_table(
    migrated: Db,
    privilege: str,
) -> None:
    row = migrated.conn.execute(
        "SELECT has_table_privilege(%s, %s, %s)",
        (ROLE, TABLE, privilege),
    ).fetchone()

    assert row is not None
    assert row[0] is False


def test_two_leases_of_one_tenant_keep_a_refusal_of_the_same_kind_each(
    migrated: Db,
) -> None:
    tenant_id, job_id, first_lease = _held(migrated)
    second_lease = _reclaim(migrated, tenant_id, job_id)

    _refusal(migrated, tenant_id, first_lease, job_id)
    _refusal(migrated, tenant_id, second_lease, job_id)

    assert _count(migrated) == 2


def test_the_same_lease_id_in_two_tenants_keeps_a_refusal_each(
    migrated: Db,
) -> None:
    tenant_a, job_a, lease_id = _held(migrated)
    tenant_b = _tenant(migrated)
    job_b = _job(migrated, tenant_b)
    _reclaim(migrated, tenant_b, job_b, lease_id)

    _refusal(migrated, tenant_a, lease_id, job_a)
    _refusal(migrated, tenant_b, lease_id, job_b)

    assert _count(migrated) == 2
