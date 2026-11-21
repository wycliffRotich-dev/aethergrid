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
import time
import uuid
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout

from app.application.public_rate_limiter import AnonymousRateLimiter
from app.infrastructure.public_read import public_pool
from app.infrastructure.public_read.postgres_public_reader import (
    MAX_LIMIT,
    PostgresPublicReader,
)
from app.presentation.public import app as public_app_module
from app.presentation.public import composition
from app.presentation.public.app import create_public_app
from app.presentation.public.responses import (
    PublicEventResponse,
    PublicJobResponse,
    PublicLeaseResponse,
    PublicNodeResponse,
    PublicWorkerResponse,
)
from tests.infrastructure.test_baseline_migration import Db
from tests.infrastructure.test_public_app_role_script import (
    APP_ROLE,
    BASE_TABLES,
    _migrated,
    _run_script,
)
from tests.support.public_app import ORIGIN, make_settings
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


def test_the_lifespan_closes_the_real_pool_when_the_app_stops(
    login: Login, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[ConnectionPool] = []

    def recording(
        database_url: str, password_file: str, password_file_setting: str
    ) -> ConnectionPool:
        made = public_pool.open_public_pool(
            database_url, password_file, password_file_setting
        )
        opened.append(made)

        return made

    monkeypatch.setattr(composition, "open_public_pool", recording)
    environment = {
        "AETHERGRID_PUBLIC_ALLOWED_ORIGIN": "https://demo.example.org",
        "AETHERGRID_PUBLIC_DATABASE_URL": login.url,
        SETTING: login.password_file,
        "AETHERGRID_PUBLIC_TRUSTED_PROXY_HOPS": "1",
    }

    try:
        app = composition.create_app(environment)

        assert len(opened) == 1
        assert not opened[0].closed

        with TestClient(app) as client:
            assert client.get("/healthz").status_code == 200
            with opened[0].connection() as conn:
                row = conn.execute("SELECT current_user").fetchone()
            assert row == (APP_ROLE,)
            assert not opened[0].closed

        assert opened[0].closed
    finally:
        for made in opened:
            made.close()


# ADR 0102, decisions 5 and 7, over the real reader and the real login.
PRIVATE_KEYS = {"tenant_id", "command", "labels", "payload"}
FIXED_BODY = b'{"error":"unavailable"}'
ROUTES = [
    ("/public/nodes", PublicNodeResponse, "nodes"),
    ("/public/jobs", PublicJobResponse, "jobs"),
    ("/public/workers", PublicWorkerResponse, "workers"),
    ("/public/leases", PublicLeaseResponse, "leases"),
    ("/public/events", PublicEventResponse, "events"),
]


def _keys(value: Any) -> set[str]:
    keys: set[str] = set()

    if isinstance(value, dict):
        keys |= set(value)
        for inner in value.values():
            keys |= _keys(inner)
    elif isinstance(value, list):
        for inner in value:
            keys |= _keys(inner)

    return keys


def _app(reader: PostgresPublicReader) -> FastAPI:
    limiter = AnonymousRateLimiter(
        client_capacity=50,
        client_refill_per_second=1.0,
        global_capacity=1000,
        global_refill_per_second=1000.0,
        max_clients=10,
    )

    return create_public_app(make_settings(), limiter=limiter, reader=reader)


def test_the_key_walk_finds_a_private_key_in_a_nested_body() -> None:
    body = [{"id": 1, "inner": [{"tenant_id": 2}]}]

    assert _keys(body) == {"id", "inner", "tenant_id"}
    assert _keys(body) & PRIVATE_KEYS == {"tenant_id"}


@pytest.mark.parametrize(
    ("path", "model", "table"), ROUTES, ids=[route[0] for route in ROUTES]
)
def test_a_route_serves_the_scoped_rows_of_the_real_reader(
    login: Login, pool: ConnectionPool, path: str, model: Any, table: str
) -> None:
    owner = login.db.conn.execute(f"SELECT count(*) FROM {table}").fetchone()
    assert owner == (2,), f"{table}: both tenants must have a row"

    reader = PostgresPublicReader(pool)
    records = getattr(reader, "list_" + table)(100)

    response = TestClient(_app(reader)).get(path)

    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body] == [str(login.chain.of(table))]
    assert body == [model.from_record(r).model_dump(mode="json") for r in records]
    assert _keys(body).isdisjoint(PRIVATE_KEYS)


def test_a_closed_pool_is_one_fixed_503(
    login: Login, caplog: pytest.LogCaptureFixture
) -> None:
    opened = public_pool.open_public_pool(login.url, login.password_file, SETTING)
    app = _app(PostgresPublicReader(opened))
    opened.close()

    with caplog.at_level(logging.ERROR):
        response = TestClient(app).get("/public/nodes", headers={"Origin": ORIGIN})

    assert response.status_code == 503
    assert response.content == FIXED_BODY
    assert response.headers["access-control-allow-origin"] == ORIGIN
    errors = [record.exc_info[1] for record in caplog.records if record.exc_info]
    assert any(isinstance(error, PoolClosed) for error in errors)
    surfaces = (response.text, str(response.headers), caplog.text)
    assert _leaks(_secrets(login), surfaces) == []


def test_a_refusal_of_the_database_is_one_fixed_503_and_only_that_route(
    login: Login, pool: ConnectionPool, caplog: pytest.LogCaptureFixture
) -> None:
    login.db.conn.execute(f"REVOKE SELECT ON public_nodes FROM {APP_ROLE}")

    with pool.connection() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT 1 FROM public_nodes")

    client = TestClient(_app(PostgresPublicReader(pool)))

    with caplog.at_level(logging.ERROR):
        refused = client.get("/public/nodes", headers={"Origin": ORIGIN})

    assert refused.status_code == 503
    assert refused.content == FIXED_BODY
    assert client.get("/public/jobs").status_code == 200
    kinds = _logged_errors(caplog)
    assert any(isinstance(e, psycopg.errors.InsufficientPrivilege) for e in kinds)
    surfaces = (refused.text, str(refused.headers), caplog.text)
    assert _leaks(_secrets(login), surfaces) == []


def _secrets(login: Login) -> list[str]:
    return [login.password, login.url, login.password_file]


def _leaks(secrets: list[str], surfaces: tuple[str, ...]) -> list[str]:
    return [s for s in secrets if any(s in surface for surface in surfaces)]


def _logged_errors(caplog: pytest.LogCaptureFixture) -> list[BaseException]:
    return [r.exc_info[1] for r in caplog.records if r.exc_info and r.exc_info[1]]


def _shown_tenant(login: Login) -> uuid.UUID:
    row = login.db.conn.execute("SELECT tenant_id FROM public_demo_scope").fetchone()
    assert row is not None
    return row[0]


def test_the_leak_check_finds_a_secret_on_any_surface() -> None:
    assert _leaks(["s3cret", "other"], ("fine", "has s3cret inside")) == ["s3cret"]
    assert _leaks(["s3cret"], ("fine", "also fine")) == []


def test_an_exhausted_pool_is_one_fixed_503_and_the_pool_recovers(
    login: Login, pool: ConnectionPool, caplog: pytest.LogCaptureFixture
) -> None:
    client = TestClient(_app(PostgresPublicReader(pool)))
    timeout = public_pool.POOL_TIMEOUT_SECONDS

    with ExitStack() as held:
        for _ in range(public_pool.POOL_MAX_SIZE):
            held.enter_context(pool.connection())

        started = time.monotonic()
        with caplog.at_level(logging.ERROR):
            response = client.get("/public/nodes", headers={"Origin": ORIGIN})
        waited = time.monotonic() - started

    assert response.status_code == 503
    assert response.content == FIXED_BODY
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert timeout * 0.9 <= waited < timeout + 3
    assert any(isinstance(e, PoolTimeout) for e in _logged_errors(caplog))
    surfaces = (response.text, str(response.headers), caplog.text)
    assert _leaks(_secrets(login), surfaces) == []
    assert client.get("/public/nodes").status_code == 200


def test_a_route_returns_at_most_the_reader_maximum_even_when_asked_for_more(
    login: Login, pool: ConnectionPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = _shown_tenant(login)
    for index in range(MAX_LIMIT + 4):
        seed_chain(login.db.conn, tenant, name=f"n-{index:04d}")

    wanted: dict[str, set[str]] = {}
    for _, _, table in ROUTES:
        rows = login.db.conn.execute(
            f"SELECT id FROM {table} WHERE tenant_id = %s", (tenant,)
        ).fetchall()
        assert len(rows) == MAX_LIMIT + 5, f"{table}: not enough rows to test the cap"
        wanted[table] = {str(row[0]) for row in rows}

    client = TestClient(_app(PostgresPublicReader(pool)))

    def check(expected: int) -> None:
        for path, _, table in ROUTES:
            ids = [row["id"] for row in client.get(path).json()]
            assert len(ids) == expected, path
            assert len(set(ids)) == expected, path
            assert set(ids) <= wanted[table], path

    check(min(public_app_module.ROW_LIMIT, MAX_LIMIT))

    monkeypatch.setattr(public_app_module, "ROW_LIMIT", MAX_LIMIT * 100)

    check(MAX_LIMIT)
