"""
ADR 0104, decisions 4 to 6, against a real database.

The tests of open_public_pool so far use a stand-in for the pool. These log in
for real, as the login role of the public app (ADR 0099), with the password
that scripts/create_public_app_role.sql stored, through the function that the
public app will call. Each check that a login is refused or limited is paired
with one that shows it able to fail. The password of the owner is removed from
the environment, so libpq can never stand in for the right one.

The role belongs to the cluster, so no test drops it. Its search path is
pointed at the scratch schema of the test and reset in a finally.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from app.infrastructure.public_read import public_pool
from app.infrastructure.public_read.postgres_public_reader import (
    PostgresPublicReader,
)
from tests.infrastructure.test_baseline_migration import Db
from tests.infrastructure.test_public_app_role_script import (
    APP_ROLE,
    BASE_TABLES,
    _migrated,
    _run_script,
)
from tests.support.public_views import Chain, make_tenant, seed_chain, set_scope

SETTING = "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE"
MESSAGE = (
    "the public database pool could not open its first connection, "
    f"check the database URL and {SETTING}"
)
TABLES = ["nodes", "jobs", "workers", "leases", "events"]


@dataclass(frozen=True)
class Login:
    db: Db
    url: str
    password: str
    password_file: str
    chain: Chain


@pytest.fixture
def db(test_database_url: str) -> Iterator[Db]:
    schema = f"public_login_{uuid.uuid4().hex[:12]}"
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


def _app_url(database_url: str, port: int | None = None) -> str:
    parts = urlparse(database_url)
    chosen = parts.port if port is None else port
    netloc = f"{APP_ROLE}@{parts.hostname}"

    if chosen:
        netloc += f":{chosen}"

    return urlunparse(parts._replace(netloc=netloc))


@pytest.fixture
def login(
    db: Db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Login]:
    schema = _migrated(db)
    shown = make_tenant(db.conn, "shown")
    other = make_tenant(db.conn, "other")
    set_scope(db.conn, shown)
    chain = seed_chain(db.conn, shown)
    seed_chain(db.conn, other)
    password = secrets.token_hex(24)

    done = _run_script(db, schema, tmp_path, password=password)

    assert done.returncode == 0, done.stderr
    db.conn.execute(f'ALTER ROLE {APP_ROLE} SET search_path TO "{schema}"')
    secret = tmp_path / "pool_password"
    secret.write_text(password)
    monkeypatch.delenv("PGPASSWORD", raising=False)

    try:
        yield Login(
            db=db,
            url=_app_url(db.url),
            password=password,
            password_file=str(secret),
            chain=chain,
        )
    finally:
        db.conn.execute(f"ALTER ROLE {APP_ROLE} RESET search_path")


@pytest.fixture
def pool(login: Login) -> Iterator[ConnectionPool]:
    opened = public_pool.open_public_pool(login.url, login.password_file, SETTING)
    try:
        yield opened
    finally:
        opened.close()


def _fail(
    url: str, password_file: str, caplog: pytest.LogCaptureFixture
) -> RuntimeError:
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(RuntimeError) as err:
            public_pool.open_public_pool(url, password_file, SETTING)

    return err.value


def test_the_pool_logs_in_as_the_public_app_role(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        row = conn.execute("SELECT current_user, session_user").fetchone()

    assert row == (APP_ROLE, APP_ROLE)


def test_the_reader_reads_the_five_views_through_the_real_login(
    login: Login, pool: ConnectionPool
) -> None:
    for table in TABLES:
        owner = login.db.conn.execute(f"SELECT count(*) FROM {table}").fetchone()
        assert owner == (2,), f"{table}: both tenants must have a row"

    reader = PostgresPublicReader(pool)

    assert [r.id for r in reader.list_nodes(100)] == [login.chain.node]
    assert [r.id for r in reader.list_jobs(100)] == [login.chain.job]
    assert [r.id for r in reader.list_workers(100)] == [login.chain.worker]
    assert [r.id for r in reader.list_leases(100)] == [login.chain.lease]
    assert [r.id for r in reader.list_events(100)] == [login.chain.event]


def test_the_login_cannot_read_a_base_table(pool: ConnectionPool) -> None:
    readable: list[str] = []

    with pool.connection() as conn:
        for table in BASE_TABLES:
            try:
                conn.execute(f"SELECT 1 FROM {table}")
            except psycopg.errors.InsufficientPrivilege:
                continue

            readable.append(table)

    assert readable == []


def test_a_deliberate_grant_makes_the_same_read_succeed(
    login: Login, pool: ConnectionPool
) -> None:
    with pool.connection() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT count(*) FROM nodes")

    login.db.conn.execute(f"GRANT SELECT ON nodes TO {APP_ROLE}")

    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM nodes").fetchone() == (2,)


def test_the_options_take_effect_and_beat_the_defaults_of_the_role(
    login: Login, pool: ConnectionPool
) -> None:
    with pool.connection() as conn:
        assert conn.execute("SHOW statement_timeout").fetchone() == ("2s",)
        assert conn.execute("SHOW default_transaction_read_only").fetchone() == (
            "on",
        )
        assert conn.execute("SHOW transaction_read_only").fetchone() == ("on",)

    with psycopg.connect(
        login.url, password=login.password, autocommit=True
    ) as plain:
        assert plain.execute("SHOW statement_timeout").fetchone() == ("5s",)
        assert plain.execute("SHOW default_transaction_read_only").fetchone() == (
            "off",
        )


def test_a_query_longer_than_the_timeout_is_cancelled(
    login: Login, pool: ConnectionPool
) -> None:
    with pool.connection() as conn:
        with pytest.raises(psycopg.errors.QueryCanceled):
            conn.execute("SELECT pg_sleep(3)")

    with psycopg.connect(
        login.url, password=login.password, autocommit=True
    ) as plain:
        assert plain.execute("SELECT pg_sleep(3)").fetchone() is not None


def test_a_wrong_password_ends_as_the_fixed_message(
    login: Login, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    wrong = "wrong-" + secrets.token_hex(12)
    wrong_file = tmp_path / "wrong_password"
    wrong_file.write_text(wrong)

    error = _fail(login.url, str(wrong_file), caplog)

    assert str(error) == MESSAGE
    assert error.__cause__ is None
    assert error.__suppress_context__ is True

    for secret in (wrong, login.password):
        assert secret not in repr(error)
        assert secret not in caplog.text


def test_an_unreachable_host_ends_as_the_fixed_message(
    login: Login, caplog: pytest.LogCaptureFixture
) -> None:
    error = _fail(_app_url(login.url, port=1), login.password_file, caplog)

    assert str(error) == MESSAGE
    assert login.password not in repr(error)
    assert login.password not in caplog.text


def test_the_driver_logs_hold_neither_the_password_nor_the_url_string(
    login: Login, caplog: pytest.LogCaptureFixture
) -> None:
    url = _app_url(login.url, port=1)

    _fail(url, login.password_file, caplog)

    assert any(
        record.name.startswith("psycopg") for record in caplog.records
    ), "the driver logged nothing, so this test would pass for nothing"
    assert login.password not in caplog.text
    assert url not in caplog.text
    assert login.password_file not in caplog.text
