"""
ADR 0109: migration 0010 creates the two views of the lease records.

public_lease_reclaims shows the leases that reclaim removed (ADR 0107) and
public_lease_refusals shows the renews and releases that were refused
(ADR 0108). Each view names its columns, runs with owner rights, is
security_barrier and joins public_demo_scope on tenant_id, like the five
views of migration 0007. The migration grants the role nothing. These tests
give the role USAGE on a scratch schema and SELECT on the two views, the way
the operator script will, and check what it can then reach. Each denial of a
base table is paired with a deliberate grant that makes the same statement
succeed, so the denial is proven able to fail.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from tests.infrastructure import test_public_read_views_migration as views_0007
from tests.infrastructure.test_baseline_migration import Db
from tests.support.public_views import ROLE, make_tenant, seed_chain, set_scope

VERSION = 10

NEW_VIEW_COLUMNS = {
    "public_lease_reclaims": [
        "id",
        "lease_id",
        "worker_id",
        "job_id",
        "lease_acquired_at",
        "lease_expires_at",
        "reclaimed_at",
        "recovered_by",
    ],
    "public_lease_refusals": [
        "id",
        "lease_id",
        "worker_id",
        "job_id",
        "operation",
        "reason",
        "refused_at",
    ],
}
NEW_VIEWS = sorted(NEW_VIEW_COLUMNS)
SEVEN_VIEWS = sorted([*views_0007.VIEWS, *NEW_VIEWS])

BASE_TABLE_OF = {
    "public_lease_reclaims": "lease_reclaims",
    "public_lease_refusals": "lease_refusals",
}
RECORD_TABLES = sorted(BASE_TABLE_OF.values())
RELATIONS = NEW_VIEWS + RECORD_TABLES

DENIED_WRITE = (
    psycopg.errors.InsufficientPrivilege,
    psycopg.errors.FeatureNotSupported,
    psycopg.errors.WrongObjectType,
    psycopg.errors.ObjectNotInPrerequisiteState,
)

WRITE_STATEMENTS = [
    ("update", "UPDATE {view} SET id = gen_random_uuid()"),
    ("delete", "DELETE FROM {view}"),
    ("insert", "INSERT INTO {view} (id) VALUES (gen_random_uuid())"),
    ("truncate", "TRUNCATE {view}"),
]
WRITES = [
    pytest.param(view, template.format(view=view), id=f"{view}-{kind}")
    for view in NEW_VIEWS
    for kind, template in WRITE_STATEMENTS
]


@dataclass(frozen=True)
class Records:
    reclaim: uuid.UUID
    refusal: uuid.UUID

    def of(self, view: str) -> uuid.UUID:
        return {
            "public_lease_reclaims": self.reclaim,
            "public_lease_refusals": self.refusal,
        }[view]


@pytest.fixture
def db(test_database_url: str) -> Iterator[Db]:
    schema = f"lease_record_views_{uuid.uuid4().hex[:12]}"
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


def _migrated(db: Db) -> str:
    applied = db.run_up_to(VERSION)
    assert VERSION in applied, f"migration {VERSION:04d} does not exist yet"
    row = db.conn.execute("SELECT current_schema()").fetchone()
    assert row is not None
    return str(row[0])


def _allow_new_views(db: Db, schema: str) -> None:
    """Test only. This is what the operator script will do on the demo database."""
    db.conn.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO {ROLE}')
    for view in NEW_VIEWS:
        db.conn.execute(f"GRANT SELECT ON {view} TO {ROLE}")


def _as_role(
    db: Db, statement: str, params: tuple[Any, ...] | None = None
) -> list[tuple[Any, ...]]:
    with db.conn.transaction():
        db.conn.execute(f"SET LOCAL ROLE {ROLE}")
        return db.conn.execute(statement, params).fetchall()


def _seed_records(conn: psycopg.Connection[Any], tenant_id: uuid.UUID) -> Records:
    """
    A job with a reclaim record and a refusal for the same lease. Every value
    that a view exposes differs from the others, so a test that compares
    fields notices two columns that were swapped.
    """
    chain = seed_chain(conn, tenant_id)
    now = datetime.now(UTC)
    reclaim = uuid.uuid4()
    refusal = uuid.uuid4()
    lease_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO lease_reclaims (id, tenant_id, lease_id, worker_id, job_id, "
        "lease_acquired_at, lease_expires_at, reclaimed_at, recovered_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'offline_node')",
        (
            reclaim,
            tenant_id,
            lease_id,
            uuid.uuid4(),
            chain.job,
            now - timedelta(seconds=61),
            now - timedelta(seconds=31),
            now - timedelta(seconds=2),
        ),
    )
    conn.execute(
        "INSERT INTO lease_refusals (id, tenant_id, lease_id, worker_id, job_id, "
        "operation, reason, refused_at) "
        "VALUES (%s, %s, %s, %s, %s, 'release', 'lease_not_current', %s)",
        (refusal, tenant_id, lease_id, uuid.uuid4(), chain.job, now),
    )
    return Records(reclaim=reclaim, refusal=refusal)


def test_the_migration_adds_exactly_the_two_views(db: Db) -> None:
    schema = _migrated(db)

    rows = db.conn.execute(
        "SELECT viewname FROM pg_views WHERE schemaname = %s", (schema,)
    ).fetchall()

    assert sorted(row[0] for row in rows) == SEVEN_VIEWS


@pytest.mark.parametrize("view", NEW_VIEWS)
def test_each_new_view_has_exactly_the_named_columns(db: Db, view: str) -> None:
    schema = _migrated(db)

    rows = db.conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (schema, view),
    ).fetchall()

    assert sorted(row[0] for row in rows) == sorted(NEW_VIEW_COLUMNS[view])


def test_no_new_view_exposes_a_private_column(db: Db) -> None:
    schema = _migrated(db)

    rows = db.conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = ANY(%s)",
        (schema, NEW_VIEWS),
    ).fetchall()

    assert rows, "the check below must have columns to look at"
    assert [r for r in rows if r[1] in views_0007.PRIVATE_COLUMNS] == []


def test_the_new_views_are_security_barrier_and_not_security_invoker(
    db: Db,
) -> None:
    schema = _migrated(db)

    rows = db.conn.execute(
        "SELECT c.relname, coalesce(c.reloptions, ARRAY[]::text[]) "
        "FROM pg_class c WHERE c.relnamespace = %s::regnamespace "
        "AND c.relkind = 'v' AND c.relname = ANY(%s)",
        (f'"{schema}"', NEW_VIEWS),
    ).fetchall()

    assert sorted(row[0] for row in rows) == NEW_VIEWS
    for name, options in rows:
        assert "security_barrier=true" in options, name
        assert not [o for o in options if o.startswith("security_invoker")], name


@pytest.mark.parametrize("relation", RELATIONS)
def test_the_migration_grants_the_role_nothing_on_a_new_relation(
    db: Db, relation: str
) -> None:
    schema = _migrated(db)

    row = db.conn.execute(
        "SELECT has_table_privilege(%s::name, %s::text, %s::text)",
        (
            ROLE,
            f'"{schema}"."{relation}"',
            "SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER",
        ),
    ).fetchone()

    assert row == (False,), relation


@pytest.mark.parametrize("view", NEW_VIEWS)
def test_an_empty_scope_shows_no_rows(db: Db, view: str) -> None:
    schema = _migrated(db)
    tenant = make_tenant(db.conn, "a")
    _seed_records(db.conn, tenant)
    _allow_new_views(db, schema)

    assert _as_role(db, f"SELECT count(*) FROM {view}") == [(0,)]

    set_scope(db.conn, tenant)
    assert _as_role(db, f"SELECT count(*) FROM {view}") == [(1,)]


@pytest.mark.parametrize("view", NEW_VIEWS)
def test_a_new_view_shows_only_the_scoped_tenant(db: Db, view: str) -> None:
    schema = _migrated(db)
    tenant_a = make_tenant(db.conn, "a")
    tenant_b = make_tenant(db.conn, "b")
    records_a = _seed_records(db.conn, tenant_a)
    records_b = _seed_records(db.conn, tenant_b)
    set_scope(db.conn, tenant_a)
    _allow_new_views(db, schema)

    shown = _as_role(db, f"SELECT id::text FROM {view}")
    assert shown == [(str(records_a.of(view)),)]

    db.conn.execute("UPDATE public_demo_scope SET tenant_id = %s", (tenant_b,))
    shown = _as_role(db, f"SELECT id::text FROM {view}")
    assert shown == [(str(records_b.of(view)),)]


@pytest.mark.parametrize("view", NEW_VIEWS)
def test_each_view_row_is_the_row_of_its_base_table(db: Db, view: str) -> None:
    schema = _migrated(db)
    tenant = make_tenant(db.conn, "a")
    records = _seed_records(db.conn, tenant)
    set_scope(db.conn, tenant)
    _allow_new_views(db, schema)
    columns = ", ".join(NEW_VIEW_COLUMNS[view])
    row_id = records.of(view)

    expected = db.conn.execute(
        f"SELECT {columns} FROM {BASE_TABLE_OF[view]} WHERE id = %s", (row_id,)
    ).fetchall()
    shown = _as_role(db, f"SELECT {columns} FROM {view} WHERE id = %s", (row_id,))

    assert len(expected) == 1
    assert shown == expected


@pytest.mark.parametrize("table", RECORD_TABLES)
def test_the_role_cannot_read_a_record_table_even_with_the_views(
    db: Db, table: str
) -> None:
    schema = _migrated(db)
    _allow_new_views(db, schema)

    with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
        _as_role(db, f"SELECT 1 FROM {table}")
    assert table in str(refused.value)

    db.conn.execute(f"GRANT SELECT ON {table} TO {ROLE}")
    _as_role(db, f"SELECT 1 FROM {table}")


@pytest.mark.parametrize(("view", "statement"), WRITES)
def test_the_role_cannot_write_through_a_new_view(
    db: Db, view: str, statement: str
) -> None:
    schema = _migrated(db)
    _allow_new_views(db, schema)

    # A view that joins the scope table cannot be updated at all, so no grant
    # makes these succeed. The privilege check below is what pins the grant.
    row = db.conn.execute(
        "SELECT has_table_privilege(%s::name, %s::text, "
        "'INSERT, UPDATE, DELETE, TRUNCATE')",
        (ROLE, f'"{schema}"."{view}"'),
    ).fetchone()
    assert row == (False,), view

    with pytest.raises(DENIED_WRITE):
        _as_role(db, statement)
