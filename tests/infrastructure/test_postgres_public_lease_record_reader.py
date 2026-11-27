"""
ADR 0109. The Postgres reader of the two lease record views.

The method is the one of the reader tests for the first five views. Every
test runs the reader as the real read role, in a scratch schema that holds
migration 0010, through a pool that has the options the public pool will
have. A reader tested as the owner would pass even when the role lacked a
grant, and a query that named a base table would pass too. Each isolation
check is paired with a count taken as the owner, so it is shown able to fail.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.application.public_read_port import (
    PublicLeaseReclaimRecord,
    PublicLeaseRefusalRecord,
)
from app.infrastructure.public_read import postgres_public_reader as reader_module
from app.infrastructure.public_read.postgres_public_reader import (
    PostgresPublicReader,
)
from tests.infrastructure.test_baseline_migration import Db
from tests.support.public_views import (
    LEASE_RECORD_VIEWS_MIGRATION,
    ROLE,
    allow_lease_record_views,
    current_schema,
    make_tenant,
    seed_lease_record,
    set_scope,
)


@dataclass(frozen=True)
class Spec:
    method: str
    table: str
    record: type
    order_field: str


SPECS = [
    Spec(
        "list_lease_reclaims",
        "lease_reclaims",
        PublicLeaseReclaimRecord,
        "reclaimed_at",
    ),
    Spec(
        "list_lease_refusals",
        "lease_refusals",
        PublicLeaseRefusalRecord,
        "refused_at",
    ),
]
EACH_VIEW = [pytest.param(spec, id=spec.method) for spec in SPECS]


@dataclass(frozen=True)
class World:
    db: Db
    schema: str
    tenant: uuid.UUID
    other: uuid.UUID


class ExplodingPool:
    """A pool that must never be used."""

    def connection(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the pool must not be used")


@pytest.fixture
def db(test_database_url: str) -> Iterator[Db]:
    schema = f"public_lease_reader_{uuid.uuid4().hex[:12]}"
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
def world(db: Db) -> World:
    applied = db.run_up_to(LEASE_RECORD_VIEWS_MIGRATION)
    assert LEASE_RECORD_VIEWS_MIGRATION in applied, "migration 0010 was not applied"
    schema = current_schema(db.conn)
    shown = make_tenant(db.conn, "shown")
    hidden = make_tenant(db.conn, "hidden")
    set_scope(db.conn, shown)
    allow_lease_record_views(db.conn, schema)

    return World(db=db, schema=schema, tenant=shown, other=hidden)


def _become_the_read_role(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"SET ROLE {ROLE}")


@pytest.fixture
def pool(world: World) -> Iterator[ConnectionPool]:
    opened = ConnectionPool(
        world.db.url,
        min_size=1,
        max_size=2,
        timeout=2.0,
        open=False,
        configure=_become_the_read_role,
        kwargs={
            "autocommit": True,
            "options": (
                f"-c search_path={world.schema} "
                "-c default_transaction_read_only=on"
            ),
        },
    )
    opened.open(wait=True, timeout=5.0)
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def reader(pool: ConnectionPool) -> PostgresPublicReader:
    return PostgresPublicReader(pool)


def read(reader: PostgresPublicReader, spec: Spec, limit: Any) -> list[Any]:
    return list(getattr(reader, spec.method)(limit))


def test_the_fixture_connects_as_the_read_role_and_not_the_owner(
    pool: ConnectionPool, world: World
) -> None:
    owner_count = world.db.conn.execute(
        "SELECT count(*) FROM lease_reclaims"
    ).fetchone()
    assert owner_count is not None

    with pool.connection() as conn:
        assert conn.execute("SELECT current_user").fetchone() == (ROLE,)

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT 1 FROM lease_reclaims")


@pytest.mark.parametrize("spec", EACH_VIEW)
class TestTenantIsolation:
    def test_only_the_scoped_tenants_rows_are_returned(
        self, world: World, reader: PostgresPublicReader, spec: Spec
    ) -> None:
        shown = {
            seed_lease_record(world.db.conn, world.tenant).of(spec.table)
            for _ in range(2)
        }
        for _ in range(3):
            seed_lease_record(world.db.conn, world.other)

        owner_count = world.db.conn.execute(
            f"SELECT count(*) FROM {spec.table}"
        ).fetchone()
        assert owner_count == (5,)

        assert {record.id for record in read(reader, spec, 100)} == shown

    def test_with_no_scope_nothing_is_returned(
        self, world: World, reader: PostgresPublicReader, spec: Spec
    ) -> None:
        seed_lease_record(world.db.conn, world.tenant)
        assert len(read(reader, spec, 100)) == 1

        world.db.conn.execute("DELETE FROM public_demo_scope")

        assert read(reader, spec, 100) == []

    def test_the_scope_row_alone_chooses_the_tenant(
        self, world: World, reader: PostgresPublicReader, spec: Spec
    ) -> None:
        seed_lease_record(world.db.conn, world.tenant)
        hidden = seed_lease_record(world.db.conn, world.other).of(spec.table)

        world.db.conn.execute(
            "UPDATE public_demo_scope SET tenant_id = %s", (world.other,)
        )

        assert [record.id for record in read(reader, spec, 100)] == [hidden]


@pytest.mark.parametrize("spec", EACH_VIEW)
class TestRecords:
    def test_every_field_equals_the_same_column_of_its_row(
        self, world: World, reader: PostgresPublicReader, spec: Spec
    ) -> None:
        for _ in range(3):
            seed_lease_record(world.db.conn, world.tenant)

        records = read(reader, spec, 100)
        columns = [field.name for field in dataclasses.fields(spec.record)]

        assert len(records) == 3

        for record in records:
            assert isinstance(record, spec.record)

            with world.db.conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    f"SELECT {', '.join(columns)} FROM {spec.table} WHERE id = %s",
                    (record.id,),
                )
                row = cursor.fetchone()

            assert dataclasses.asdict(record) == row


class TestLimit:
    @pytest.mark.parametrize("spec", EACH_VIEW)
    @pytest.mark.parametrize("asked", [4, 101, 10**6, 2**63, 2**70])
    def test_a_limit_above_the_maximum_is_cut_to_it(
        self,
        world: World,
        reader: PostgresPublicReader,
        spec: Spec,
        asked: int,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(reader_module, "MAX_LIMIT", 3)
        for _ in range(5):
            seed_lease_record(world.db.conn, world.tenant)

        assert len(read(reader, spec, asked)) == 3

    @pytest.mark.parametrize("spec", EACH_VIEW)
    def test_a_limit_below_the_maximum_is_honoured(
        self,
        world: World,
        reader: PostgresPublicReader,
        spec: Spec,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(reader_module, "MAX_LIMIT", 3)
        for _ in range(5):
            seed_lease_record(world.db.conn, world.tenant)

        assert len(read(reader, spec, 1)) == 1
        assert len(read(reader, spec, 2)) == 2
        assert len(read(reader, spec, 3)) == 3

    @pytest.mark.parametrize("spec", EACH_VIEW)
    @pytest.mark.parametrize("bad", [0, -1, -100, -(2**70)])
    def test_a_limit_below_one_is_refused_before_the_database_is_used(
        self, spec: Spec, bad: int
    ) -> None:
        reader = PostgresPublicReader(cast(ConnectionPool, ExplodingPool()))

        with pytest.raises(ValueError):
            read(reader, spec, bad)

    @pytest.mark.parametrize("spec", EACH_VIEW)
    @pytest.mark.parametrize("bad", [True, False, 1.0, 2.5, "5", None, b"5", [1]])
    def test_a_limit_that_is_not_an_integer_is_refused_before_the_database_is_used(
        self, spec: Spec, bad: Any
    ) -> None:
        reader = PostgresPublicReader(cast(ConnectionPool, ExplodingPool()))

        with pytest.raises(TypeError):
            read(reader, spec, bad)


@pytest.mark.parametrize("spec", EACH_VIEW)
class TestOrder:
    def test_each_read_is_newest_first_with_the_id_last(
        self, world: World, reader: PostgresPublicReader, spec: Spec
    ) -> None:
        count = 6
        # Earlier rows get larger ids, so rows that tie on the order key are
        # inserted in the opposite order to the one the id must give them.
        ids = sorted((uuid.uuid4() for _ in range(count)), reverse=True)
        offsets = [2, 0, 3, 1, 3, 2]
        base = datetime(2026, 1, 1, tzinfo=UTC)

        for index in range(count):
            moment = base + timedelta(seconds=offsets[index])
            seed_lease_record(
                world.db.conn,
                world.tenant,
                reclaim_id=ids[index],
                refusal_id=ids[index],
                reclaimed_at=moment,
                refused_at=moment,
            )

        records = read(reader, spec, 100)
        by_id = sorted(records, key=lambda record: record.id)
        expected = sorted(
            by_id,
            key=lambda record: getattr(record, spec.order_field),
            reverse=True,
        )

        assert len(records) == count
        assert records == expected

        keys = {getattr(record, spec.order_field) for record in records}
        assert len(keys) < count, "the rows must tie, or the id is untested"

    def test_two_reads_return_the_same_order(
        self, world: World, reader: PostgresPublicReader, spec: Spec
    ) -> None:
        for _ in range(5):
            seed_lease_record(world.db.conn, world.tenant)

        assert read(reader, spec, 100) == read(reader, spec, 100)


@pytest.mark.parametrize("spec", EACH_VIEW)
class TestTheReaderReadsAsTheRole:
    def test_a_missing_grant_breaks_the_read_and_a_new_one_mends_it(
        self, world: World, reader: PostgresPublicReader, spec: Spec
    ) -> None:
        view = f"public_{spec.table}"
        seed_lease_record(world.db.conn, world.tenant)
        assert len(read(reader, spec, 10)) == 1

        world.db.conn.execute(f"REVOKE SELECT ON {view} FROM {ROLE}")

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            read(reader, spec, 10)

        world.db.conn.execute(f"GRANT SELECT ON {view} TO {ROLE}")

        assert len(read(reader, spec, 10)) == 1

    def test_a_failed_read_returns_its_connection_to_the_pool(
        self, world: World, reader: PostgresPublicReader, spec: Spec
    ) -> None:
        view = f"public_{spec.table}"
        seed_lease_record(world.db.conn, world.tenant)
        world.db.conn.execute(f"REVOKE SELECT ON {view} FROM {ROLE}")

        # The pool holds two connections, so a leak shows on the third call.
        for _ in range(6):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                read(reader, spec, 1)

        world.db.conn.execute(f"GRANT SELECT ON {view} TO {ROLE}")

        for _ in range(6):
            assert len(read(reader, spec, 1)) == 1
