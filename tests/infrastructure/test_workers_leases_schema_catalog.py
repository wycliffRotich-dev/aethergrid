from __future__ import annotations

import psycopg
import pytest
from psycopg.rows import tuple_row
from psycopg_pool import ConnectionPool

# ADR 0075 properties 1 to 3: the database itself refuses a worker, a
# running job or a lease that crosses tenants. The migration tests prove
# it by building rows. This asks the migrated database what it enforces,
# so the claim is checked on every run and not only when a migration is
# written.

EXPECTED_FOREIGN_KEYS = {
    "workers_node_same_tenant": (
        "workers", ["node_id", "tenant_id"], "nodes", ["id", "tenant_id"],
    ),
    "workers_running_job_same_tenant": (
        "workers", ["running_job_id", "tenant_id"], "jobs", ["id", "tenant_id"],
    ),
    "leases_worker_same_tenant": (
        "leases", ["worker_id", "tenant_id"], "workers", ["id", "tenant_id"],
    ),
    "leases_job_same_tenant": (
        "leases", ["job_id", "tenant_id"], "jobs", ["id", "tenant_id"],
    ),
}
REQUIRED_TENANT_TABLES = ["leases", "workers"]

_FOREIGN_KEYS = """
SELECT c.conname,
       c.conrelid::regclass::text,
       ARRAY(SELECT a.attname
             FROM unnest(c.conkey) WITH ORDINALITY k(attnum, ord)
             JOIN pg_attribute a
               ON a.attrelid = c.conrelid AND a.attnum = k.attnum
             ORDER BY k.ord),
       c.confrelid::regclass::text,
       ARRAY(SELECT a.attname
             FROM unnest(c.confkey) WITH ORDINALITY k(attnum, ord)
             JOIN pg_attribute a
               ON a.attrelid = c.confrelid AND a.attnum = k.attnum
             ORDER BY k.ord)
FROM pg_constraint c
WHERE c.contype = 'f' AND c.conname = ANY(%s)
"""

_NULLABLE = """
SELECT table_name, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND column_name = 'tenant_id'
  AND table_name = ANY(%s)
"""


def schema_problems(conn) -> list[str]:
    """Return what the database does not enforce, one line each."""
    problems: list[str] = []
    cursor = conn.cursor(row_factory=tuple_row)

    found = {
        row[0]: (row[1], list(row[2]), row[3], list(row[4]))
        for row in cursor.execute(
            _FOREIGN_KEYS, (list(EXPECTED_FOREIGN_KEYS),)
        ).fetchall()
    }
    for name, expected in EXPECTED_FOREIGN_KEYS.items():
        if name not in found:
            problems.append(f"missing foreign key {name}")
        elif found[name] != expected:
            problems.append(f"{name} is {found[name]}, expected {expected}")

    nullable = dict(
        cursor.execute(_NULLABLE, (REQUIRED_TENANT_TABLES,)).fetchall()
    )
    for table in REQUIRED_TENANT_TABLES:
        if nullable.get(table) != "NO":
            problems.append(f"{table}.tenant_id is not NOT NULL")
    return problems


@pytest.fixture(scope="module")
def pool(test_database_url: str):
    test_pool = ConnectionPool(
        test_database_url,
        min_size=1,
        max_size=2,
        open=True,
        kwargs={"autocommit": True},
    )
    yield test_pool
    test_pool.close()


def test_the_database_enforces_the_same_tenant_rules(pool) -> None:
    with pool.connection() as conn:
        assert schema_problems(conn) == []


def test_the_check_notices_a_dropped_foreign_key(test_database_url, pool) -> None:
    with psycopg.connect(test_database_url) as conn:
        conn.execute("ALTER TABLE leases DROP CONSTRAINT leases_job_same_tenant")
        assert schema_problems(conn) == [
            "missing foreign key leases_job_same_tenant"
        ]
        conn.rollback()

    with pool.connection() as conn:
        assert schema_problems(conn) == []


def test_the_check_notices_a_nullable_tenant(test_database_url, pool) -> None:
    with psycopg.connect(test_database_url) as conn:
        conn.execute("ALTER TABLE workers ALTER COLUMN tenant_id DROP NOT NULL")
        assert schema_problems(conn) == ["workers.tenant_id is not NOT NULL"]
        conn.rollback()

    with pool.connection() as conn:
        assert schema_problems(conn) == []
