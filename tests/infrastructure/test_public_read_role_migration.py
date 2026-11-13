"""
ADR 0097: a role for the public demo that can do nothing.

Migration 0006 creates aethergrid_public_read as a NOLOGIN group role and
grants it nothing. A role belongs to the cluster and not to a schema, so
these tests leave it in place. One test drops it when nothing holds it
and recreates it in a finally. Each test runs in its own scratch schema, and
every grant a test makes lands on an object of that schema and goes with
it. The only change a test makes to the role itself is restored in a
finally. Each denial is paired with a deliberate grant that makes the
same statement succeed, so the denial is proven able to fail.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest

from app.infrastructure.migrations.runner import (
    MIGRATIONS_DIR,
    MigrationError,
    apply_migrations,
    load_migrations,
)
from tests.infrastructure.test_baseline_migration import Db

ROLE = "aethergrid_public_read"
VERSION = 6

READ_TABLES = ["api_keys", "tenants", "jobs", "schema_migrations"]

WRITES = [
    pytest.param(
        "INSERT INTO tenants (id, name, created_at) "
        "VALUES (gen_random_uuid(), 'x', now())",
        "INSERT ON tenants",
        id="insert",
    ),
    pytest.param("UPDATE jobs SET priority = 1", "UPDATE ON jobs", id="update"),
    pytest.param("DELETE FROM jobs", "DELETE ON jobs", id="delete"),
    pytest.param("TRUNCATE api_keys", "TRUNCATE ON api_keys", id="truncate"),
]


@pytest.fixture
def db(test_database_url: str) -> Iterator[Db]:
    schema = f"public_role_{uuid.uuid4().hex[:12]}"
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
    name = f"public_role_two_{uuid.uuid4().hex[:12]}"
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


def _allow_schema_use(db: Db, schema: str) -> None:
    """Test only. Without USAGE every denial would be a schema denial."""
    db.conn.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO {ROLE}')


def _as_role(db: Db, statement: str) -> None:
    with db.conn.transaction():
        db.conn.execute(f"SET LOCAL ROLE {ROLE}")
        db.conn.execute(statement)


def test_the_role_has_no_power_of_its_own(db: Db) -> None:
    _migrated(db)

    row = db.conn.execute(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolcanlogin, "
        "rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s",
        (ROLE,),
    ).fetchone()

    assert row == (False, False, False, False, False, False)


def test_the_role_has_no_members_and_belongs_to_no_role(db: Db) -> None:
    _migrated(db)

    members = db.conn.execute(
        "SELECT count(*) FROM pg_auth_members m "
        "JOIN pg_roles r ON r.oid = m.roleid WHERE r.rolname = %s",
        (ROLE,),
    ).fetchone()
    memberships = db.conn.execute(
        "SELECT count(*) FROM pg_auth_members m "
        "JOIN pg_roles r ON r.oid = m.member WHERE r.rolname = %s",
        (ROLE,),
    ).fetchone()

    assert members == (0,)
    assert memberships == (0,)


def test_the_migration_grants_the_role_nothing(db: Db) -> None:
    schema = _migrated(db)

    tables = [
        row[0]
        for row in db.conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = %s", (schema,)
        ).fetchall()
    ]
    assert "jobs" in tables, "the loop below must have something to check"

    for table in tables:
        row = db.conn.execute(
            "SELECT has_table_privilege(%s::name, %s::text, %s::text)",
            (
                ROLE,
                f'"{schema}"."{table}"',
                "SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER",
            ),
        ).fetchone()
        assert row == (False,), table

    for privilege in ("USAGE", "CREATE"):
        row = db.conn.execute(
            "SELECT has_schema_privilege(%s::name, %s::text, %s::text)",
            (ROLE, schema, privilege),
        ).fetchone()
        assert row == (False,), privilege


def test_applying_the_migration_in_a_second_schema_succeeds(db: Db) -> None:
    _migrated(db)

    with _second_schema(db) as other:
        assert VERSION in _migrate_in(db, other)

    row = db.conn.execute(
        "SELECT count(*) FROM pg_roles WHERE rolname = %s", (ROLE,)
    ).fetchone()
    assert row == (1,)


def test_an_existing_role_that_can_log_in_is_refused_and_not_changed(
    db: Db,
) -> None:
    _migrated(db)

    with _second_schema(db) as other:
        db.conn.execute(f"ALTER ROLE {ROLE} LOGIN")
        try:
            with pytest.raises((MigrationError, psycopg.Error)) as refused:
                _migrate_in(db, other)

            message = f"{refused.value} {refused.value.__cause__}"
            assert ROLE in message
            assert "LOGIN" in message

            row = db.conn.execute(
                f'SELECT count(*) FROM "{other}".schema_migrations '
                "WHERE version = %s",
                (VERSION,),
            ).fetchone()
            assert row == (0,)

            still = db.conn.execute(
                "SELECT rolcanlogin FROM pg_roles WHERE rolname = %s", (ROLE,)
            ).fetchone()
            assert still == (True,), "the migration must not alter the role"
        finally:
            db.conn.execute(f"ALTER ROLE {ROLE} NOLOGIN")


@pytest.mark.parametrize("table", READ_TABLES)
def test_the_role_cannot_read_a_table_until_it_is_granted(
    db: Db, table: str
) -> None:
    schema = _migrated(db)
    _allow_schema_use(db, schema)

    with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
        _as_role(db, f"SELECT 1 FROM {table}")
    assert table in str(refused.value)

    db.conn.execute(f"GRANT SELECT ON {table} TO {ROLE}")
    _as_role(db, f"SELECT 1 FROM {table}")


@pytest.mark.parametrize(("statement", "grant"), WRITES)
def test_the_role_cannot_write_until_it_is_granted(
    db: Db, statement: str, grant: str
) -> None:
    schema = _migrated(db)
    _allow_schema_use(db, schema)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _as_role(db, statement)

    db.conn.execute(f"GRANT {grant} TO {ROLE}")
    _as_role(db, statement)


def test_the_role_cannot_create_an_object_until_it_is_granted(db: Db) -> None:
    schema = _migrated(db)
    _allow_schema_use(db, schema)

    with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
        _as_role(db, "CREATE TABLE role_probe (id integer)")
    assert schema in str(refused.value)

    db.conn.execute(f'GRANT CREATE ON SCHEMA "{schema}" TO {ROLE}')
    _as_role(db, "CREATE TABLE role_probe (id integer)")


def test_the_role_cannot_run_a_program_on_the_server(db: Db) -> None:
    schema = _migrated(db)
    _allow_schema_use(db, schema)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _as_role(db, "COPY (SELECT 1) TO PROGRAM 'true'")


POWERS = [
    pytest.param("SUPERUSER", "rolsuper", id="superuser"),
    pytest.param("CREATEDB", "rolcreatedb", id="createdb"),
    pytest.param("CREATEROLE", "rolcreaterole", id="createrole"),
    pytest.param("REPLICATION", "rolreplication", id="replication"),
    pytest.param("BYPASSRLS", "rolbypassrls", id="bypassrls"),
]


@pytest.mark.parametrize(("power", "column"), POWERS)
def test_an_existing_role_with_a_power_is_refused_and_not_changed(
    db: Db, power: str, column: str
) -> None:
    _migrated(db)

    with _second_schema(db) as other:
        db.conn.execute(f"ALTER ROLE {ROLE} {power}")
        try:
            with pytest.raises((MigrationError, psycopg.Error)) as refused:
                _migrate_in(db, other)

            message = f"{refused.value} {refused.value.__cause__}"
            assert ROLE in message
            assert power in message

            row = db.conn.execute(
                f'SELECT count(*) FROM "{other}".schema_migrations '
                "WHERE version = %s",
                (VERSION,),
            ).fetchone()
            assert row == (0,)

            still = db.conn.execute(
                f"SELECT {column} FROM pg_roles WHERE rolname = %s", (ROLE,)
            ).fetchone()
            assert still == (True,), "the migration must not alter the role"
        finally:
            db.conn.execute(f"ALTER ROLE {ROLE} NO{power}")


GRANTS = [
    pytest.param(["GRANT SELECT ON jobs TO {role}"], [], id="table"),
    pytest.param(['GRANT USAGE ON SCHEMA "{schema}" TO {role}'], [], id="schema"),
    pytest.param(["GRANT SELECT (id) ON jobs TO {role}"], [], id="column"),
    pytest.param(
        [
            "CREATE FUNCTION role_probe() RETURNS integer "
            "LANGUAGE sql AS 'SELECT 1'",
            "GRANT EXECUTE ON FUNCTION role_probe() TO {role}",
        ],
        [],
        id="function",
    ),
    pytest.param(
        [
            'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
            "GRANT SELECT ON TABLES TO {role}"
        ],
        [],
        id="default-privileges",
    ),
    pytest.param(
        [
            "DO $$ BEGIN EXECUTE format("
                "'GRANT CONNECT ON DATABASE %I TO {role}', "
                "current_database()); END $$"
        ],
        [
            "DO $$ BEGIN EXECUTE format("
                "'REVOKE CONNECT ON DATABASE %I FROM {role}', "
                "current_database()); END $$"
        ],
        id="database",
    ),
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


@pytest.mark.parametrize(("setup", "teardown"), GRANTS)
def test_an_existing_role_that_holds_a_grant_is_refused_and_not_changed(
    db: Db, setup: list[str], teardown: list[str]
) -> None:
    schema = _migrated(db)

    with _second_schema(db) as other:
        try:
            for statement in setup:
                db.conn.execute(statement.format(role=ROLE, schema=schema))

            with pytest.raises((MigrationError, psycopg.Error)) as refused:
                _migrate_in(db, other)

            message = f"{refused.value} {refused.value.__cause__}"
            assert ROLE in message
            assert "has been granted" in message

            row = db.conn.execute(
                f'SELECT count(*) FROM "{other}".schema_migrations '
                "WHERE version = %s",
                (VERSION,),
            ).fetchone()
            assert row == (0,)
        finally:
            for statement in teardown:
                db.conn.execute(statement.format(role=ROLE, schema=schema))


def _reachable(db: Db, schema: str) -> list[str]:
    """What the role can use in the schema without any grant of its own."""
    relations = db.conn.execute(
        "SELECT c.relname FROM pg_class c "
        "WHERE c.relnamespace = %s::regnamespace "
        "AND c.relkind IN ('r', 'v', 'm', 'p') "
        "AND has_table_privilege(%s::name, c.oid, "
        "'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER')",
        (f'"{schema}"', ROLE),
    ).fetchall()
    functions = db.conn.execute(
        "SELECT p.proname FROM pg_proc p "
        "WHERE p.pronamespace = %s::regnamespace "
        "AND has_function_privilege(%s::name, p.oid, 'EXECUTE')",
        (f'"{schema}"', ROLE),
    ).fetchall()
    return sorted(row[0] for row in relations + functions)


def test_the_role_reaches_nothing_in_the_schema_through_public(db: Db) -> None:
    schema = _migrated(db)

    assert _reachable(db, schema) == []

    # A new function is executable by PUBLIC unless that is revoked, so this
    # proves the check above is able to find something.
    db.conn.execute(
        "CREATE FUNCTION role_probe() RETURNS integer LANGUAGE sql AS 'SELECT 1'"
    )

    assert _reachable(db, schema) == ["role_probe"]


RACE_APPLICATION = "role_race_second_runner"
RACE_WAIT_SECONDS = 30.0

CREATE_THE_ROLE = (
    f"CREATE ROLE {ROLE} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
    "NOREPLICATION NOBYPASSRLS"
)


def _drop_the_role_or_skip(db: Db) -> None:
    """Make the role absent, or skip without having changed anything."""
    row = db.conn.execute(
        "SELECT count(*) FROM pg_auth_members m "
        "JOIN pg_roles r ON r.oid IN (m.roleid, m.member) "
        "WHERE r.rolname = %s",
        (ROLE,),
    ).fetchone()
    if row != (0,):
        pytest.skip(f"{ROLE} has memberships, so this test does not drop it")
    try:
        db.conn.execute(f"DROP ROLE IF EXISTS {ROLE}")
    except psycopg.errors.DependentObjectsStillExist:
        pytest.skip(f"{ROLE} still holds objects, so this test does not drop it")


def _a_runner_is_waiting_on_a_lock(db: Db) -> bool:
    row = db.conn.execute(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE application_name = %s AND wait_event_type = 'Lock'",
        (RACE_APPLICATION,),
    ).fetchone()
    return row is not None and row[0] > 0


def test_a_runner_that_loses_the_race_to_create_the_role_still_succeeds(
    db: Db,
) -> None:
    _drop_the_role_or_skip(db)
    first = psycopg.connect(db.url)
    outcome: dict[str, object] = {}

    try:
        with _second_schema(db) as other:

            def second_runner() -> None:
                try:
                    outcome["applied"] = apply_migrations(
                        db.url,
                        [
                            m
                            for m in load_migrations(MIGRATIONS_DIR)
                            if m.version <= VERSION
                        ],
                        connect_kwargs={
                            "options": f"-c search_path={other} "
                            f"-c application_name={RACE_APPLICATION}"
                        },
                        lock_key=uuid.uuid4().int >> 66,
                        lock_timeout_seconds=10.0,
                    )
                except BaseException as error:  # reported by the asserts below
                    outcome["error"] = error

            # The first runner has created the role and not yet committed.
            first.execute(CREATE_THE_ROLE)
            thread = threading.Thread(target=second_runner)
            thread.start()

            deadline = time.monotonic() + RACE_WAIT_SECONDS
            while not _a_runner_is_waiting_on_a_lock(db):
                if not thread.is_alive() or time.monotonic() > deadline:
                    break
                time.sleep(0.05)
            waiting = _a_runner_is_waiting_on_a_lock(db)

            first.commit()
            thread.join(RACE_WAIT_SECONDS)

            assert waiting, "the second runner never reached CREATE ROLE"
            assert not thread.is_alive(), "the second runner never finished"
            assert "error" not in outcome, outcome.get("error")
            assert VERSION in outcome["applied"]  # type: ignore[operator]

            row = db.conn.execute(
                "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                "rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s",
                (ROLE,),
            ).fetchone()
            assert row == (False, False, False, False, False, False)
    finally:
        first.close()
        left = db.conn.execute(
            "SELECT count(*) FROM pg_roles WHERE rolname = %s", (ROLE,)
        ).fetchone()
        if left == (0,):
            db.conn.execute(CREATE_THE_ROLE)
