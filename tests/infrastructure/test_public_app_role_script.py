"""
ADR 0099: the public app logs in as a role of its own.

scripts/create_public_app_role.sql creates aethergrid_public_app, a login
role with its own direct grants. A role belongs to the cluster and not to a
schema, so these tests never drop it. Each test runs in its own scratch
schema, and every grant a test makes lands on an object of that schema and
goes with it. A test that changes the role restores it in a finally. The
password in these tests is a random value that is written to a temporary file
and never printed, and no test connects with it.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.infrastructure.migrations.runner import MIGRATIONS_DIR, load_migrations
from tests.infrastructure.test_baseline_migration import Db
from tests.infrastructure.test_public_read_views_migration import VIEWS

APP_ROLE = "aethergrid_public_app"
GROUP_ROLE = "aethergrid_public_read"
CONNECTION_LIMIT = 10
STATEMENT_TIMEOUT = "5s"

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "create_public_app_role.sql"

POWERS = [
    ("SUPERUSER", "rolsuper"),
    ("CREATEDB", "rolcreatedb"),
    ("CREATEROLE", "rolcreaterole"),
    ("REPLICATION", "rolreplication"),
    ("BYPASSRLS", "rolbypassrls"),
]

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


@pytest.fixture
def db(test_database_url: str) -> Iterator[Db]:
    schema = f"public_app_{uuid.uuid4().hex[:12]}"
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
    versions = [m for m in load_migrations(MIGRATIONS_DIR) if m.version <= 7]
    from app.infrastructure.migrations.runner import apply_migrations

    apply_migrations(
        db.url,
        versions,
        connect_kwargs=db.connect_kwargs,
        lock_key=db.lock_key,
        lock_timeout_seconds=10.0,
    )
    row = db.conn.execute("SELECT current_schema()").fetchone()
    assert row is not None
    return str(row[0])


def _grant_group_role(db: Db, schema: str) -> None:
    """What scripts/grant_public_read.sql does, so the two roles can be compared."""
    db.conn.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO {GROUP_ROLE}')
    for view in VIEWS:
        db.conn.execute(f"GRANT SELECT ON {view} TO {GROUP_ROLE}")


def _run_script(
    db: Db, schema: str, tmp_path: Path, password: str | None = None
) -> subprocess.CompletedProcess[str]:
    secret = tmp_path / "password"
    secret.write_text(password if password is not None else secrets.token_hex(24))
    secret.chmod(0o600)
    options = f"-c search_path={schema}"
    variables = [
        "-v", "ON_ERROR_STOP=1",
        "-v", f"connection_limit={CONNECTION_LIMIT}",
        "-v", f"statement_timeout={STATEMENT_TIMEOUT}",
        "-f", "-",
    ]
    if shutil.which("psql"):
        return subprocess.run(
            ["psql", db.url, *variables],
            input=SCRIPT.read_text(),
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PGOPTIONS": options,
                "AETHERGRID_PUBLIC_APP_PASSWORD_FILE": str(secret),
            },
            cwd=SCRIPT.parents[1],
            check=False,
        )
    pytest.skip(
        "needs a psql on this machine: the Postgres container is read-only, "
        "so a password file cannot be placed where its psql can read it"
    )


def _role_row(db: Db, name: str) -> tuple[Any, ...] | None:
    return db.conn.execute(
        "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
        "rolreplication, rolbypassrls, rolconnlimit "
        "FROM pg_roles WHERE rolname = %s",
        (name,),
    ).fetchone()


def _held(db: Db, schema: str, role: str) -> list[tuple[str, str]]:
    rows = db.conn.execute(
        "SELECT c.relname, p.privilege FROM pg_class c "
        "CROSS JOIN (VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'), "
        "('TRUNCATE'), ('REFERENCES'), ('TRIGGER')) AS p(privilege) "
        "WHERE c.relnamespace = %s::regnamespace "
        "AND c.relkind IN ('r', 'v', 'm', 'p') "
        "AND has_table_privilege(%s::name, c.oid, p.privilege) ORDER BY 1, 2",
        (f'"{schema}"', role),
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def test_the_script_creates_a_login_role_with_none_of_the_powers(
    db: Db, tmp_path: Path
) -> None:
    schema = _migrated(db)
    _grant_group_role(db, schema)

    done = _run_script(db, schema, tmp_path)

    assert done.returncode == 0, done.stderr
    row = _role_row(db, APP_ROLE)
    assert row is not None
    assert row[:6] == (True, False, False, False, False, False)


def test_the_script_sets_the_connection_limit_and_the_statement_timeout(
    db: Db, tmp_path: Path
) -> None:
    schema = _migrated(db)
    _grant_group_role(db, schema)

    done = _run_script(db, schema, tmp_path)

    assert done.returncode == 0, done.stderr
    row = _role_row(db, APP_ROLE)
    assert row is not None and row[6] == CONNECTION_LIMIT
    settings = db.conn.execute(
        "SELECT s.setconfig FROM pg_db_role_setting s "
        "JOIN pg_roles r ON r.oid = s.setrole "
        "WHERE r.rolname = %s AND s.setdatabase = 0",
        (APP_ROLE,),
    ).fetchone()
    assert settings is not None
    assert f"statement_timeout={STATEMENT_TIMEOUT}" in settings[0]


def test_the_script_gives_the_role_the_five_views_and_schema_usage_only(
    db: Db, tmp_path: Path
) -> None:
    schema = _migrated(db)
    _grant_group_role(db, schema)

    _run_script(db, schema, tmp_path)

    assert _held(db, schema, APP_ROLE) == [(view, "SELECT") for view in VIEWS]
    row = db.conn.execute(
        "SELECT has_schema_privilege(%s::name, %s::text, 'USAGE'), "
        "has_schema_privilege(%s::name, %s::text, 'CREATE')",
        (APP_ROLE, schema, APP_ROLE, schema),
    ).fetchone()
    assert row == (True, False)


@pytest.mark.parametrize("table", BASE_TABLES)
def test_the_role_cannot_read_a_base_table(
    db: Db, tmp_path: Path, table: str
) -> None:
    schema = _migrated(db)
    _grant_group_role(db, schema)
    _run_script(db, schema, tmp_path)

    row = db.conn.execute(
        "SELECT has_table_privilege(%s::name, %s::text, 'SELECT')",
        (APP_ROLE, f'"{schema}"."{table}"'),
    ).fetchone()
    assert row == (False,), table


def test_the_two_roles_hold_the_same_privileges(db: Db, tmp_path: Path) -> None:
    schema = _migrated(db)
    _grant_group_role(db, schema)

    _run_script(db, schema, tmp_path)

    assert _held(db, schema, APP_ROLE) == _held(db, schema, GROUP_ROLE)


def test_the_role_is_not_a_member_of_the_group_role_and_has_no_member(
    db: Db, tmp_path: Path
) -> None:
    schema = _migrated(db)
    _grant_group_role(db, schema)

    _run_script(db, schema, tmp_path)

    row = db.conn.execute(
        "SELECT count(*) FROM pg_auth_members m "
        "JOIN pg_roles r ON r.oid IN (m.roleid, m.member) WHERE r.rolname = %s",
        (APP_ROLE,),
    ).fetchone()
    assert row == (0,)


def test_the_script_never_prints_the_password(db: Db, tmp_path: Path) -> None:
    schema = _migrated(db)
    _grant_group_role(db, schema)
    password = secrets.token_hex(24)

    done = _run_script(db, schema, tmp_path, password=password)

    assert password not in done.stdout
    assert password not in done.stderr


def test_the_script_stores_a_hashed_password_and_not_the_text(
    db: Db, tmp_path: Path
) -> None:
    schema = _migrated(db)
    _grant_group_role(db, schema)
    password = secrets.token_hex(24)

    _run_script(db, schema, tmp_path, password=password)

    row = db.conn.execute(
        "SELECT rolpassword FROM pg_authid WHERE rolname = %s", (APP_ROLE,)
    ).fetchone()
    assert row is not None and row[0] is not None
    assert row[0].startswith("SCRAM-SHA-256$")
    assert password not in row[0]


def test_running_the_script_twice_leaves_the_same_privileges(
    db: Db, tmp_path: Path
) -> None:
    schema = _migrated(db)
    _grant_group_role(db, schema)
    _run_script(db, schema, tmp_path)
    first = _held(db, schema, APP_ROLE)

    done = _run_script(db, schema, tmp_path)

    assert done.returncode == 0, done.stderr
    assert _held(db, schema, APP_ROLE) == first


@pytest.mark.parametrize(("power", "column"), POWERS)
def test_the_script_refuses_an_existing_role_with_a_power(
    db: Db, tmp_path: Path, power: str, column: str
) -> None:
    schema = _migrated(db)
    _grant_group_role(db, schema)
    _run_script(db, schema, tmp_path)
    db.conn.execute(f"ALTER ROLE {APP_ROLE} {power}")
    try:
        done = _run_script(db, schema, tmp_path)

        assert done.returncode != 0
        assert power in done.stderr
        still = db.conn.execute(
            f"SELECT {column} FROM pg_roles WHERE rolname = %s", (APP_ROLE,)
        ).fetchone()
        assert still == (True,), "the script must not alter the role"
    finally:
        db.conn.execute(f"ALTER ROLE {APP_ROLE} NO{power}")


def test_the_script_refuses_an_existing_role_with_a_privilege_on_another_table(
    db: Db, tmp_path: Path
) -> None:
    schema = _migrated(db)
    _grant_group_role(db, schema)
    _run_script(db, schema, tmp_path)
    db.conn.execute(f"GRANT SELECT ON tenants TO {APP_ROLE}")

    done = _run_script(db, schema, tmp_path)

    assert done.returncode != 0
    assert "tenants" in done.stderr
    assert ("tenants", "SELECT") in _held(db, schema, APP_ROLE)


def test_the_script_refuses_an_empty_password_file_and_keeps_the_old_password(
    db: Db, tmp_path: Path
) -> None:
    schema = _migrated(db)
    _grant_group_role(db, schema)
    _run_script(db, schema, tmp_path)
    before = db.conn.execute(
        "SELECT rolpassword FROM pg_authid WHERE rolname = %s", (APP_ROLE,)
    ).fetchone()

    done = _run_script(db, schema, tmp_path, password="")

    after = db.conn.execute(
        "SELECT rolpassword FROM pg_authid WHERE rolname = %s", (APP_ROLE,)
    ).fetchone()
    assert before is not None and before[0] is not None
    assert after == before, "an empty file must not change the password"

    assert done.returncode != 0
    assert "empty" in done.stderr


MEMBERSHIPS = [
    pytest.param(
        ["GRANT pg_monitor TO {role}"],
        ["REVOKE pg_monitor FROM {role}"],
        id="member-of-a-role",
    ),
    pytest.param(
        [
            "DROP ROLE IF EXISTS aethergrid_probe_member",
            "CREATE ROLE aethergrid_probe_member NOLOGIN",
            "GRANT {role} TO aethergrid_probe_member",
        ],
        ["DROP ROLE IF EXISTS aethergrid_probe_member"],
        id="has-a-member",
    ),
]


@pytest.mark.parametrize(("setup", "teardown"), MEMBERSHIPS)
def test_the_script_refuses_an_existing_role_with_a_membership(
    db: Db, tmp_path: Path, setup: list[str], teardown: list[str]
) -> None:
    schema = _migrated(db)
    _grant_group_role(db, schema)
    _run_script(db, schema, tmp_path)
    try:
        for statement in setup:
            db.conn.execute(statement.format(role=APP_ROLE))

        done = _run_script(db, schema, tmp_path)

        assert done.returncode != 0
        assert "membership" in done.stderr or "member" in done.stderr
    finally:
        for statement in teardown:
            db.conn.execute(statement.format(role=APP_ROLE))
