"""
ADR 0098: the public demo reads views and nothing else.

Migration 0007 creates five views with named columns, owner rights and
security_barrier, and a one-row table that says which tenant they show. It
grants the role nothing. These tests give the role USAGE on a scratch schema
and SELECT on the views, the way the operator script will, and check what it
can then reach. Every grant lands on an object of the scratch schema and goes
with it when the schema is dropped. Each denial of a base table is paired
with a deliberate grant that makes the same statement succeed, so the denial
is proven able to fail.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg
import pytest

from app.infrastructure.migrations.runner import (
    MIGRATIONS_DIR,
    apply_migrations,
    load_migrations,
)
from tests.infrastructure.test_baseline_migration import Db

ROLE = "aethergrid_public_read"
VERSION = 7

VIEW_COLUMNS = {
    "public_nodes": [
        "id",
        "name",
        "capacity_cpu_cores",
        "capacity_memory_mib",
        "capacity_vram_mib",
        "available_cpu_cores",
        "available_memory_mib",
        "available_vram_mib",
        "last_seen_at",
        "draining",
    ],
    "public_jobs": [
        "id",
        "cpu_cores",
        "memory_mib",
        "vram_mib",
        "priority",
        "max_retries",
        "retry_count",
        "status",
        "assigned_node_id",
        "submitted_at",
        "started_at",
        "completed_at",
        "execution_timeout_seconds",
    ],
    "public_workers": [
        "id",
        "node_id",
        "status",
        "running_job_id",
        "last_seen_at",
    ],
    "public_leases": ["id", "worker_id", "job_id", "acquired_at", "expires_at"],
    "public_events": [
        "id",
        "aggregate_id",
        "aggregate_type",
        "event_type",
        "occurred_at",
    ],
}
VIEWS = sorted(VIEW_COLUMNS)

KEY_OF_VIEW = {
    "public_nodes": "node",
    "public_jobs": "job",
    "public_workers": "worker",
    "public_leases": "lease",
    "public_events": "event",
}

PRIVATE_COLUMNS = {
    "tenant_id",
    "command",
    "constraints",
    "labels",
    "exit_code",
    "cancellation_requested_at",
    "managed_by",
    "payload",
}

BASE_TABLES = [
    "nodes",
    "jobs",
    "workers",
    "leases",
    "events",
    "tenants",
    "api_keys",
    "public_demo_scope",
]

DENIED_WRITE = (
    psycopg.errors.InsufficientPrivilege,
    psycopg.errors.FeatureNotSupported,
    psycopg.errors.WrongObjectType,
    psycopg.errors.ObjectNotInPrerequisiteState,
)

WRITES = [
    pytest.param("UPDATE public_jobs SET priority = 1", id="update"),
    pytest.param("DELETE FROM public_jobs", id="delete"),
    pytest.param(
        "INSERT INTO public_jobs (id) VALUES (gen_random_uuid())", id="insert"
    ),
    pytest.param("TRUNCATE public_jobs", id="truncate"),
]


@pytest.fixture
def db(test_database_url: str) -> Iterator[Db]:
    schema = f"public_views_{uuid.uuid4().hex[:12]}"
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


@contextmanager
def _second_schema(db: Db) -> Iterator[str]:
    name = f"public_views_two_{uuid.uuid4().hex[:12]}"
    db.conn.execute(f'CREATE SCHEMA "{name}"')
    try:
        yield name
    finally:
        db.conn.execute(f'DROP SCHEMA "{name}" CASCADE')


def _migrate_in(db: Db, schema: str) -> list[int]:
    return apply_migrations(
        db.url,
        [m for m in load_migrations(MIGRATIONS_DIR) if m.version <= VERSION],
        connect_kwargs={"options": f"-c search_path={schema}"},
        lock_key=uuid.uuid4().int >> 66,
        lock_timeout_seconds=10.0,
    )


def _tenant(db: Db, name: str) -> str:
    tenant_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO tenants (id, name, created_at) VALUES (%s, %s, now())",
        (tenant_id, name),
    )
    return tenant_id


def _seed(db: Db, tenant_id: str) -> dict[str, str]:
    """One node, job, worker, lease and event for the tenant."""
    ids = {key: str(uuid.uuid4()) for key in KEY_OF_VIEW.values()}
    db.conn.execute(
        "INSERT INTO nodes (id, name, capacity_cpu_cores, capacity_memory_mib, "
        "capacity_vram_mib, available_cpu_cores, available_memory_mib, "
        "available_vram_mib, last_seen_at, tenant_id) "
        "VALUES (%s, 'node', 8, 16384, 0, 8, 16384, 0, now(), %s)",
        (ids["node"], tenant_id),
    )
    db.conn.execute(
        "INSERT INTO jobs (id, cpu_cores, memory_mib, status, submitted_at, "
        "tenant_id) VALUES (%s, 1, 512, 'RUNNING', now(), %s)",
        (ids["job"], tenant_id),
    )
    db.conn.execute(
        "INSERT INTO workers (id, node_id, status, running_job_id, "
        "last_seen_at, tenant_id) VALUES (%s, %s, 'BUSY', %s, now(), %s)",
        (ids["worker"], ids["node"], ids["job"], tenant_id),
    )
    db.conn.execute(
        "INSERT INTO leases (id, worker_id, job_id, acquired_at, expires_at, "
        "tenant_id) VALUES (%s, %s, %s, now(), now() + interval '30 seconds', %s)",
        (ids["lease"], ids["worker"], ids["job"], tenant_id),
    )
    db.conn.execute(
        "INSERT INTO events (id, job_id, aggregate_id, aggregate_type, "
        "event_type, occurred_at, tenant_id) "
        "VALUES (%s, %s, %s, 'job', 'JOB_STARTED', now(), %s)",
        (ids["event"], ids["job"], ids["job"], tenant_id),
    )
    return ids


def _scope(db: Db, tenant_id: str) -> None:
    db.conn.execute(
        "INSERT INTO public_demo_scope (tenant_id) VALUES (%s)", (tenant_id,)
    )


def _allow_views(db: Db, schema: str) -> None:
    """Test only. This is what the operator script will do on the demo database."""
    db.conn.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO {ROLE}')
    for view in VIEWS:
        db.conn.execute(f"GRANT SELECT ON {view} TO {ROLE}")


def _as_role(db: Db, statement: str) -> list[tuple[Any, ...]]:
    with db.conn.transaction():
        db.conn.execute(f"SET LOCAL ROLE {ROLE}")
        return db.conn.execute(statement).fetchall()


def test_the_migration_creates_exactly_the_five_views(db: Db) -> None:
    schema = _migrated(db)

    rows = db.conn.execute(
        "SELECT viewname FROM pg_views WHERE schemaname = %s", (schema,)
    ).fetchall()

    assert sorted(row[0] for row in rows) == VIEWS


@pytest.mark.parametrize("view", VIEWS)
def test_each_view_has_exactly_the_named_columns(db: Db, view: str) -> None:
    schema = _migrated(db)

    rows = db.conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (schema, view),
    ).fetchall()

    assert sorted(row[0] for row in rows) == sorted(VIEW_COLUMNS[view])


def test_no_view_exposes_a_private_column(db: Db) -> None:
    schema = _migrated(db)

    rows = db.conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = ANY(%s)",
        (schema, VIEWS),
    ).fetchall()

    assert rows, "the check below must have columns to look at"
    assert [r for r in rows if r[1] in PRIVATE_COLUMNS] == []


def test_the_views_are_security_barrier_and_not_security_invoker(db: Db) -> None:
    schema = _migrated(db)

    rows = db.conn.execute(
        "SELECT c.relname, coalesce(c.reloptions, ARRAY[]::text[]) "
        "FROM pg_class c WHERE c.relnamespace = %s::regnamespace "
        "AND c.relkind = 'v'",
        (f'"{schema}"',),
    ).fetchall()

    assert sorted(row[0] for row in rows) == VIEWS
    for name, options in rows:
        assert "security_barrier=true" in options, name
        assert not [o for o in options if o.startswith("security_invoker")], name


def test_the_scope_table_refuses_a_second_row(db: Db) -> None:
    _migrated(db)
    _scope(db, _tenant(db, "a"))
    other = _tenant(db, "b")

    with pytest.raises(psycopg.errors.UniqueViolation):
        _scope(db, other)


def test_the_scope_table_refuses_a_row_that_is_not_the_single_one(db: Db) -> None:
    _migrated(db)
    tenant = _tenant(db, "a")

    with pytest.raises(psycopg.errors.CheckViolation):
        db.conn.execute(
            "INSERT INTO public_demo_scope (singleton, tenant_id) "
            "VALUES (false, %s)",
            (tenant,),
        )


def test_the_migration_grants_the_role_nothing_on_the_views(db: Db) -> None:
    schema = _migrated(db)

    for view in VIEWS + ["public_demo_scope"]:
        row = db.conn.execute(
            "SELECT has_table_privilege(%s::name, %s::text, %s::text)",
            (
                ROLE,
                f'"{schema}"."{view}"',
                "SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER",
            ),
        ).fetchone()
        assert row == (False,), view

    row = db.conn.execute(
        "SELECT has_schema_privilege(%s::name, %s::text, 'USAGE')", (ROLE, schema)
    ).fetchone()
    assert row == (False,)


@pytest.mark.parametrize("view", VIEWS)
def test_an_empty_scope_shows_no_rows(db: Db, view: str) -> None:
    schema = _migrated(db)
    tenant = _tenant(db, "a")
    _seed(db, tenant)
    _allow_views(db, schema)

    assert _as_role(db, f"SELECT count(*) FROM {view}") == [(0,)]

    _scope(db, tenant)
    assert _as_role(db, f"SELECT count(*) FROM {view}") == [(1,)]


@pytest.mark.parametrize("view", VIEWS)
def test_a_view_shows_only_the_scoped_tenant(db: Db, view: str) -> None:
    schema = _migrated(db)
    tenant_a = _tenant(db, "a")
    tenant_b = _tenant(db, "b")
    ids_a = _seed(db, tenant_a)
    ids_b = _seed(db, tenant_b)
    _scope(db, tenant_a)
    _allow_views(db, schema)
    key = KEY_OF_VIEW[view]

    shown = _as_role(db, f"SELECT id::text FROM {view}")
    assert shown == [(ids_a[key],)]

    db.conn.execute("UPDATE public_demo_scope SET tenant_id = %s", (tenant_b,))
    shown = _as_role(db, f"SELECT id::text FROM {view}")
    assert shown == [(ids_b[key],)]


@pytest.mark.parametrize("table", BASE_TABLES)
def test_the_role_cannot_read_a_base_table_even_with_the_views(
    db: Db, table: str
) -> None:
    schema = _migrated(db)
    _allow_views(db, schema)

    with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
        _as_role(db, f"SELECT 1 FROM {table}")
    assert table in str(refused.value)

    db.conn.execute(f"GRANT SELECT ON {table} TO {ROLE}")
    _as_role(db, f"SELECT 1 FROM {table}")


@pytest.mark.parametrize("statement", WRITES)
def test_the_role_cannot_write_through_a_view(db: Db, statement: str) -> None:
    schema = _migrated(db)
    _allow_views(db, schema)

    # A view that joins the scope table cannot be updated at all, so no grant
    # makes these succeed. The privilege check below is what pins the grant.
    for view in VIEWS:
        row = db.conn.execute(
            "SELECT has_table_privilege(%s::name, %s::text, "
            "'INSERT, UPDATE, DELETE, TRUNCATE')",
            (ROLE, f'"{schema}"."{view}"'),
        ).fetchone()
        assert row == (False,), view

    with pytest.raises(DENIED_WRITE):
        _as_role(db, statement)


def test_applying_the_migration_in_a_second_schema_succeeds(db: Db) -> None:
    _migrated(db)

    with _second_schema(db) as other:
        assert VERSION in _migrate_in(db, other)


GRANT_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "grant_public_read.sql"
)


def _run_grant_script(db: Db) -> None:
    db.conn.execute(GRANT_SCRIPT.read_text())


def _held_by_the_role(db: Db, schema: str) -> list[tuple[str, str]]:
    """Every privilege the role holds on a relation of the schema."""
    rows = db.conn.execute(
        "SELECT c.relname, p.privilege "
        "FROM pg_class c "
        "CROSS JOIN (VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'), "
        "('TRUNCATE'), ('REFERENCES'), ('TRIGGER')) AS p(privilege) "
        "WHERE c.relnamespace = %s::regnamespace "
        "AND c.relkind IN ('r', 'v', 'm', 'p') "
        "AND has_table_privilege(%s::name, c.oid, p.privilege) "
        "ORDER BY 1, 2",
        (f'"{schema}"', ROLE),
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def test_the_grant_script_gives_the_role_the_five_views_and_nothing_else(
    db: Db,
) -> None:
    schema = _migrated(db)

    _run_grant_script(db)

    assert _held_by_the_role(db, schema) == [(view, "SELECT") for view in VIEWS]
    row = db.conn.execute(
        "SELECT has_schema_privilege(%s::name, %s::text, 'USAGE'), "
        "has_schema_privilege(%s::name, %s::text, 'CREATE')",
        (ROLE, schema, ROLE, schema),
    ).fetchone()
    assert row == (True, False)


def test_running_the_grant_script_twice_changes_nothing(db: Db) -> None:
    schema = _migrated(db)
    _run_grant_script(db)
    first = _held_by_the_role(db, schema)

    _run_grant_script(db)

    assert _held_by_the_role(db, schema) == first


def test_the_grant_script_refuses_when_a_view_is_missing_and_grants_nothing(
    db: Db,
) -> None:
    schema = _migrated(db)
    db.conn.execute("DROP VIEW public_jobs")

    with pytest.raises(psycopg.Error) as refused:
        _run_grant_script(db)

    assert "cannot grant: missing view(s) public_jobs" in str(refused.value)
    assert _held_by_the_role(db, schema) == []
    row = db.conn.execute(
        "SELECT has_schema_privilege(%s::name, %s::text, 'USAGE')", (ROLE, schema)
    ).fetchone()
    assert row == (False,)


def test_the_grant_script_refuses_when_the_role_holds_another_privilege(
    db: Db,
) -> None:
    schema = _migrated(db)
    db.conn.execute(f"GRANT SELECT ON tenants TO {ROLE}")

    with pytest.raises(psycopg.Error) as refused:
        _run_grant_script(db)

    assert "tenants" in str(refused.value)
    assert _held_by_the_role(db, schema) == [("tenants", "SELECT")]
    row = db.conn.execute(
        "SELECT has_schema_privilege(%s::name, %s::text, 'USAGE')", (ROLE, schema)
    ).fetchone()
    assert row == (False,)


SCOPE_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "set_public_demo_tenant.sql"
)


def _run_scope_script(db: Db, tenant_name: str) -> None:
    """Run the script with psql's :tenant_name variable filled in."""
    quoted = "'" + tenant_name.replace("'", "''") + "'"
    db.conn.execute(SCOPE_SCRIPT.read_text().replace(":'tenant_name'", quoted))


def _scoped_tenants(db: Db) -> list[str]:
    rows = db.conn.execute(
        "SELECT tenant_id::text FROM public_demo_scope"
    ).fetchall()
    return [row[0] for row in rows]


def test_the_scope_script_points_the_views_at_the_named_tenant(db: Db) -> None:
    schema = _migrated(db)
    tenant = _tenant(db, "demo")
    ids = _seed(db, tenant)
    _allow_views(db, schema)

    _run_scope_script(db, "demo")

    assert _scoped_tenants(db) == [tenant]
    assert _as_role(db, "SELECT id::text FROM public_jobs") == [(ids["job"],)]


def test_running_the_scope_script_twice_for_the_same_tenant_changes_nothing(
    db: Db,
) -> None:
    _migrated(db)
    tenant = _tenant(db, "demo")
    _run_scope_script(db, "demo")

    _run_scope_script(db, "demo")

    assert _scoped_tenants(db) == [tenant]


def test_the_scope_script_refuses_an_unknown_tenant_name_and_changes_nothing(
    db: Db,
) -> None:
    _migrated(db)

    with pytest.raises(psycopg.Error) as refused:
        _run_scope_script(db, "no-such-tenant")

    assert "no-such-tenant" in str(refused.value)
    assert _scoped_tenants(db) == []


def test_the_scope_script_refuses_to_move_the_views_to_another_tenant(
    db: Db,
) -> None:
    _migrated(db)
    first = _tenant(db, "first")
    _tenant(db, "second")
    _run_scope_script(db, "first")

    with pytest.raises(psycopg.Error) as refused:
        _run_scope_script(db, "second")

    assert "the views already show first" in str(refused.value)
    assert _scoped_tenants(db) == [first]


def test_the_scope_script_grants_the_role_nothing(db: Db) -> None:
    schema = _migrated(db)
    _tenant(db, "demo")

    _run_scope_script(db, "demo")

    assert _held_by_the_role(db, schema) == []


def _run_scope_script_with_psql(
    db: Db, schema: str, tenant_name: str
) -> subprocess.CompletedProcess[str]:
    """The path an operator takes: the real psql, one statement at a time."""
    parts = urlparse(db.url)
    options = f"-c search_path={schema}"
    variables = [
        "-v", "ON_ERROR_STOP=1", "-v", f"tenant_name={tenant_name}", "-f", "-",
    ]
    if shutil.which("psql"):
        command = ["psql", db.url, *variables]
        env = {**os.environ, "PGOPTIONS": options}
    elif shutil.which("docker"):
        command = [
            "docker", "compose", "exec", "-T", "-e", f"PGOPTIONS={options}",
            "postgres", "psql", "-U", parts.username or "neuromesh",
            "-d", parts.path.lstrip("/"), *variables,
        ]
        env = dict(os.environ)
    else:
        pytest.skip("neither psql nor docker is available")
    return subprocess.run(
        command,
        input=SCOPE_SCRIPT.read_text(),
        capture_output=True,
        text=True,
        env=env,
        cwd=SCOPE_SCRIPT.parents[1],
        check=False,
    )


def test_the_scope_script_works_through_psql(db: Db) -> None:
    schema = _migrated(db)
    tenant = _tenant(db, "demo")

    done = _run_scope_script_with_psql(db, schema, "demo")

    assert done.returncode == 0, done.stderr
    assert _scoped_tenants(db) == [tenant]


def test_the_scope_script_refuses_an_unknown_name_through_psql(db: Db) -> None:
    schema = _migrated(db)

    done = _run_scope_script_with_psql(db, schema, "no-such-tenant")

    assert done.returncode != 0
    assert "no tenant is named no-such-tenant" in done.stderr
    assert _scoped_tenants(db) == []
