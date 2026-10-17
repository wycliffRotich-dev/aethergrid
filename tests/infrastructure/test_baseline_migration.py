from __future__ import annotations

import hashlib
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
    NO_TRANSACTION_MARKER,
    apply_migrations,
    load_migrations,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL = ROOT / "app/infrastructure/repositories/schema.sql"
PRE_TENANCY = Path(__file__).resolve().parent / "schema_pre_tenancy.sql"
BASELINE = MIGRATIONS_DIR / "0001_baseline.sql"

_FINGERPRINT = """
SELECT 'column', c.relname, a.attname,
       format_type(a.atttypid, a.atttypmod), a.attnotnull::text,
       coalesce(pg_get_expr(d.adbin, d.adrelid), '')
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE c.relnamespace = current_schema()::regnamespace
  AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
UNION ALL
SELECT 'constraint', c.relname, k.conname, pg_get_constraintdef(k.oid), '', ''
FROM pg_constraint k
JOIN pg_class c ON c.oid = k.conrelid
WHERE c.relnamespace = current_schema()::regnamespace
UNION ALL
SELECT 'index', tablename, indexname, indexdef, '', ''
FROM pg_indexes WHERE schemaname = current_schema()
ORDER BY 1, 2, 3
"""


@dataclass
class Db:
    url: str
    connect_kwargs: dict[str, Any]
    lock_key: int
    conn: psycopg.Connection

    def run_baseline(self) -> list[int]:
        return self.run_up_to(1)

    def run_up_to(self, version: int) -> list[int]:
        return apply_migrations(
            self.url,
            [m for m in load_migrations(MIGRATIONS_DIR) if m.version <= version],
            connect_kwargs=self.connect_kwargs,
            lock_key=self.lock_key,
            lock_timeout_seconds=10.0,
        )

    def fingerprint(self) -> list[tuple[Any, ...]]:
        rows = self.conn.execute(_FINGERPRINT).fetchall()
        return [row for row in rows if row[1] != "schema_migrations"]


@pytest.fixture
def db(test_database_url: str) -> Iterator[Db]:
    schema = f"baseline_{uuid.uuid4().hex[:12]}"
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


def test_the_real_migration_set_is_the_baseline_and_the_events_tenant() -> None:
    migrations = load_migrations(MIGRATIONS_DIR)

    assert [m.name for m in migrations] == [
        "0001_baseline.sql",
        "0002_give_events_a_tenant.sql",
    ]
    assert migrations[0].transactional is False


def test_the_baseline_is_the_marker_plus_schema_sql_byte_for_byte() -> None:
    expected = (NO_TRANSACTION_MARKER + "\n").encode("utf-8") + SCHEMA_SQL.read_bytes()

    assert BASELINE.read_bytes() == expected


def test_no_migration_file_and_no_schema_file_contains_a_carriage_return() -> None:
    for path in [SCHEMA_SQL, *MIGRATIONS_DIR.glob("*.sql")]:
        assert b"\r" not in path.read_bytes(), path.name


def test_package_data_covers_every_migration_file() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "app.infrastructure.migrations" in text
    assert "versions/*.sql" in text


def test_the_fingerprint_sees_the_schema(db: Db) -> None:
    db.conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))

    kinds = {row[0] for row in db.fingerprint()}
    tables = {row[1] for row in db.fingerprint()}

    assert kinds == {"column", "constraint", "index"}
    assert {"tenants", "nodes", "jobs", "workers", "api_keys"} <= tables


def test_an_empty_database_gets_the_whole_schema_and_the_baseline_record(
    db: Db,
) -> None:
    assert db.run_baseline() == [1]

    tenants = db.conn.execute("SELECT id::text FROM tenants").fetchall()
    assert tenants == [(str(DEFAULT_TENANT_ID),)]
    recorded = db.conn.execute(
        "SELECT version, name, checksum FROM schema_migrations"
    ).fetchall()
    assert recorded == [
        (1, "0001_baseline.sql", hashlib.sha256(BASELINE.read_bytes()).hexdigest())
    ]


def test_a_database_built_from_schema_sql_alone_is_adopted_without_change(
    db: Db,
) -> None:
    db.conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    db.conn.execute(
        "INSERT INTO nodes (id, name, capacity_cpu_cores, capacity_memory_mib, "
        "capacity_vram_mib, available_cpu_cores, available_memory_mib, "
        "available_vram_mib, last_seen_at, tenant_id) "
        "VALUES (%s, 'kept', 8, 16384, 0, 8, 16384, 0, now(), %s)",
        (str(uuid.uuid4()), str(DEFAULT_TENANT_ID)),
    )
    before = db.fingerprint()
    assert before

    assert db.run_baseline() == [1]

    assert db.fingerprint() == before
    assert db.conn.execute("SELECT name FROM nodes").fetchall() == [("kept",)]
    assert db.conn.execute("SELECT version FROM schema_migrations").fetchall() == [(1,)]


def test_a_pre_tenancy_database_with_rows_is_upgraded_by_the_runner(
    db: Db,
) -> None:
    db.conn.execute(PRE_TENANCY.read_text(encoding="utf-8"))
    job_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO jobs (id, cpu_cores, memory_mib, status, submitted_at) "
        "VALUES (%s, 1, 512, 'QUEUED', now())",
        (job_id,),
    )

    assert db.run_baseline() == [1]

    rows = db.conn.execute("SELECT id::text, tenant_id::text FROM jobs").fetchall()
    assert rows == [(job_id, str(DEFAULT_TENANT_ID))]


def test_a_second_run_applies_nothing_and_changes_no_structure(db: Db) -> None:
    db.run_baseline()
    before = db.fingerprint()

    assert db.run_baseline() == []

    assert db.fingerprint() == before


def test_applying_schema_sql_again_after_the_baseline_changes_no_structure(
    db: Db,
) -> None:
    db.run_baseline()
    before = db.fingerprint()

    db.conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))

    assert db.fingerprint() == before
