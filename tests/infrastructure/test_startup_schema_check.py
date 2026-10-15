from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.infrastructure.migrations.runner import (
    MigrationError,
    apply_migrations,
    load_migrations,
)
from app.infrastructure.migrations.startup_check import check_schema


@dataclass
class Scratch:
    """A throwaway schema, a pool pointed at it, and a way to migrate it."""

    url: str
    options: str
    lock_key: int
    pool: ConnectionPool
    conn: psycopg.Connection

    def apply(self, migrations: Any) -> list[int]:
        return apply_migrations(
            self.url,
            migrations,
            connect_kwargs={"options": self.options},
            lock_key=self.lock_key,
        )


@pytest.fixture
def scratch(test_database_url: str) -> Iterator[Scratch]:
    schema = f"startup_{uuid.uuid4().hex[:12]}"
    options = f"-c search_path={schema}"
    with psycopg.connect(test_database_url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.execute(f'SET search_path TO "{schema}"')
        pool = ConnectionPool(
            test_database_url,
            min_size=1,
            max_size=2,
            open=True,
            kwargs={"autocommit": True, "options": options},
        )
        try:
            pool.wait(timeout=10.0)
            yield Scratch(
                url=test_database_url,
                options=options,
                lock_key=uuid.uuid4().int >> 66,
                pool=pool,
                conn=conn,
            )
        finally:
            pool.close()
            conn.execute("SET search_path TO public")
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


def _load(directory: Path, files: dict[str, str]) -> list[Any]:
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")
    return load_migrations(directory)


def test_a_migrated_database_passes(scratch: Scratch, tmp_path: Path) -> None:
    migrations = _load(tmp_path, {"0001_a.sql": "CREATE TABLE a (n integer);\n"})
    scratch.apply(migrations)

    assert check_schema(scratch.pool, migrations) == ()


def test_a_database_that_is_behind_is_refused_and_names_what_is_missing(
    scratch: Scratch,
    tmp_path: Path,
) -> None:
    first = _load(tmp_path, {"0001_a.sql": "CREATE TABLE a (n integer);\n"})
    scratch.apply(first)
    both = _load(tmp_path, {"0002_b.sql": "CREATE TABLE b (n integer);\n"})

    with pytest.raises(MigrationError, match="behind") as raised:
        check_schema(scratch.pool, both)

    assert "0002_b.sql" in str(raised.value)


def test_an_empty_history_is_behind(scratch: Scratch, tmp_path: Path) -> None:
    migrations = _load(tmp_path, {"0001_a.sql": "CREATE TABLE a (n integer);\n"})
    scratch.apply([])

    with pytest.raises(MigrationError, match="behind"):
        check_schema(scratch.pool, migrations)


def test_a_missing_bookkeeping_table_says_to_run_the_migrations(
    scratch: Scratch,
    tmp_path: Path,
) -> None:
    migrations = _load(tmp_path, {"0001_a.sql": "CREATE TABLE a (n integer);\n"})

    with pytest.raises(MigrationError, match="run the migrations"):
        check_schema(scratch.pool, migrations)


def test_the_check_never_creates_the_bookkeeping_table(
    scratch: Scratch,
    tmp_path: Path,
) -> None:
    migrations = _load(tmp_path, {"0001_a.sql": "CREATE TABLE a (n integer);\n"})

    with pytest.raises(MigrationError):
        check_schema(scratch.pool, migrations)

    row = scratch.conn.execute("SELECT to_regclass('schema_migrations')").fetchone()
    assert row == (None,)


def test_a_changed_checksum_is_refused(scratch: Scratch, tmp_path: Path) -> None:
    original = _load(tmp_path, {"0001_a.sql": "CREATE TABLE a (n integer);\n"})
    scratch.apply(original)
    edited = _load(
        tmp_path,
        {"0001_a.sql": "CREATE TABLE a (n integer, extra integer);\n"},
    )

    with pytest.raises(MigrationError, match="checksum"):
        check_schema(scratch.pool, edited)


def test_a_database_ahead_of_the_image_passes_and_reports_the_versions(
    scratch: Scratch,
    tmp_path: Path,
) -> None:
    both = _load(
        tmp_path,
        {
            "0001_a.sql": "CREATE TABLE a (n integer);\n",
            "0002_b.sql": "CREATE TABLE b (n integer);\n",
        },
    )
    scratch.apply(both)
    before = scratch.conn.execute(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()

    assert check_schema(scratch.pool, both[:1]) == (2,)

    after = scratch.conn.execute(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert after == before


def test_the_check_reads_rows_from_a_connection_that_returns_dicts(
    scratch: Scratch,
    tmp_path: Path,
) -> None:
    """
    The Postgres repositories set row_factory to dict_row on the pooled
    connections they borrow, and nothing resets it. The next borrower of
    that connection gets dict rows, so the check must not depend on the
    row factory it finds.
    """
    migrations = _load(tmp_path, {"0001_a.sql": "CREATE TABLE a (n integer);\n"})
    scratch.apply(migrations)
    with scratch.pool.connection() as conn:
        conn.row_factory = dict_row

    assert check_schema(scratch.pool, migrations) == ()
