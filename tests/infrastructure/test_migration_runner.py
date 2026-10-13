from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.infrastructure.migrations.runner import (
    NO_TRANSACTION_MARKER,
    Migration,
    MigrationError,
    _apply_locked,
    apply_migrations,
    load_migrations,
)


@dataclass
class Db:
    """A scratch Postgres schema plus the arguments that point the runner at it."""

    url: str
    connect_kwargs: dict[str, Any]
    lock_key: int
    conn: psycopg.Connection

    def run(self, migrations: Any, **overrides: Any) -> list[int]:
        kwargs: dict[str, Any] = {
            "connect_kwargs": self.connect_kwargs,
            "lock_key": self.lock_key,
            "lock_timeout_seconds": 10.0,
        }
        kwargs.update(overrides)
        return apply_migrations(self.url, migrations, **kwargs)


@pytest.fixture
def db(test_database_url: str) -> Iterator[Db]:
    """
    One throwaway schema per test, and one advisory lock key per test, so
    tests cannot block each other even if they ever run in parallel. The
    runner opens its own connections, so the schema reaches them through
    the libpq search_path option.
    """
    schema = f"migrate_{uuid.uuid4().hex[:12]}"
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


def _load(directory: Path, files: dict[str, str]) -> list[Any]:
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")
    return load_migrations(directory)


def _applied(db: Db) -> list[tuple[Any, ...]]:
    return db.conn.execute(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()


def _tables(db: Db) -> list[str]:
    rows = db.conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema() ORDER BY 1"
    ).fetchall()
    return [row[0] for row in rows]


def test_applies_missing_migrations_in_order_and_records_them(
    db: Db,
    tmp_path: Path,
) -> None:
    migrations = _load(
        tmp_path,
        {
            "0001_create.sql": "CREATE TABLE t (n integer);\n",
            "0002_fill.sql": "INSERT INTO t VALUES (1);\n",
        },
    )

    assert db.run(migrations) == [1, 2]

    assert _applied(db) == [(m.version, m.name, m.checksum) for m in migrations]
    assert db.conn.execute("SELECT n FROM t").fetchall() == [(1,)]


def test_a_second_run_applies_nothing_and_changes_nothing(
    db: Db,
    tmp_path: Path,
) -> None:
    migrations = _load(tmp_path, {"0001_create.sql": "CREATE TABLE t (n integer);\n"})
    db.run(migrations)
    query = "SELECT version, applied_at FROM schema_migrations"
    before = db.conn.execute(query).fetchall()

    assert db.run(migrations) == []

    assert db.conn.execute(query).fetchall() == before


def test_a_failing_transactional_migration_leaves_no_partial_change(
    db: Db,
    tmp_path: Path,
) -> None:
    migrations = _load(
        tmp_path,
        {"0001_boom.sql": "CREATE TABLE half (n integer);\nSELECT 1/0;\n"},
    )

    with pytest.raises(MigrationError, match="0001_boom.sql"):
        db.run(migrations)

    assert _applied(db) == []
    assert "half" not in _tables(db)


def test_a_failure_at_a_later_migration_keeps_the_earlier_ones(
    db: Db,
    tmp_path: Path,
) -> None:
    migrations = _load(
        tmp_path,
        {
            "0001_ok.sql": "CREATE TABLE ok (n integer);\n",
            "0002_boom.sql": "SELECT 1/0;\n",
            "0003_never.sql": "CREATE TABLE never (n integer);\n",
        },
    )

    with pytest.raises(MigrationError, match="0002_boom.sql"):
        db.run(migrations)

    assert [row[0] for row in _applied(db)] == [1]
    assert "ok" in _tables(db)
    assert "never" not in _tables(db)


def test_an_edited_applied_migration_is_refused(db: Db, tmp_path: Path) -> None:
    first = _load(tmp_path, {"0001_a.sql": "CREATE TABLE a (n integer);\n"})
    db.run(first)

    edited = _load(
        tmp_path,
        {
            "0001_a.sql": "CREATE TABLE a (n integer, extra integer);\n",
            "0002_b.sql": "CREATE TABLE b (n integer);\n",
        },
    )

    with pytest.raises(MigrationError, match="checksum"):
        db.run(edited)

    assert "b" not in _tables(db)


def test_a_recorded_version_with_no_file_is_refused(db: Db, tmp_path: Path) -> None:
    both = _load(
        tmp_path,
        {
            "0001_a.sql": "CREATE TABLE a (n integer);\n",
            "0002_b.sql": "CREATE TABLE b (n integer);\n",
        },
    )
    db.run(both)

    with pytest.raises(MigrationError, match="0002"):
        db.run(both[:1])


def test_a_no_transaction_migration_may_contain_its_own_transaction_control(
    db: Db,
    tmp_path: Path,
) -> None:
    migrations = _load(
        tmp_path,
        {
            "0001_base.sql": (
                f"{NO_TRANSACTION_MARKER}\n"
                "BEGIN;\nCREATE TABLE t (n integer);\nCOMMIT;\n"
            )
        },
    )
    assert not migrations[0].transactional

    assert db.run(migrations) == [1]

    assert "t" in _tables(db)
    assert [row[0] for row in _applied(db)] == [1]


def test_two_runners_started_together_apply_each_migration_once(
    db: Db,
    tmp_path: Path,
) -> None:
    migrations = _load(
        tmp_path,
        {"0001_slow.sql": "CREATE TABLE t (n integer);\nSELECT pg_sleep(1);\n"},
    )
    barrier = threading.Barrier(2)

    def run() -> list[int]:
        barrier.wait(timeout=10)
        return db.run(migrations)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run), pool.submit(run)]
        results = [future.result(timeout=30) for future in futures]

    assert sorted(results) == [[], [1]]
    assert [row[0] for row in _applied(db)] == [1]


def test_the_lock_is_released_after_a_failure(db: Db, tmp_path: Path) -> None:
    bad = _load(tmp_path, {"0001_boom.sql": "SELECT 1/0;\n"})
    with pytest.raises(MigrationError):
        db.run(bad)

    good = _load(tmp_path, {"0001_boom.sql": "CREATE TABLE t (n integer);\n"})

    assert db.run(good, lock_timeout_seconds=3.0) == [1]


def test_a_held_lock_times_out_instead_of_waiting_forever(
    db: Db,
    tmp_path: Path,
) -> None:
    migrations = _load(tmp_path, {"0001_a.sql": "CREATE TABLE t (n integer);\n"})

    with psycopg.connect(db.url, autocommit=True) as holder:
        holder.execute("SELECT pg_advisory_lock(%s::bigint)", (db.lock_key,))
        with pytest.raises(MigrationError, match="lock"):
            db.run(migrations, lock_timeout_seconds=0.5)

    assert "t" not in _tables(db)


def test_a_hole_in_the_applied_history_is_refused(db: Db, tmp_path: Path) -> None:
    migrations = _load(
        tmp_path,
        {
            "0001_a.sql": "CREATE TABLE a (n integer);\n",
            "0002_b.sql": "CREATE TABLE b (n integer);\n",
        },
    )
    db.run([])
    db.conn.execute(
        "INSERT INTO schema_migrations (version, name, checksum) VALUES (2, %s, %s)",
        (migrations[1].name, migrations[1].checksum),
    )

    with pytest.raises(MigrationError, match="0001"):
        db.run(migrations)

    assert "a" not in _tables(db)


def test_an_empty_migration_set_still_creates_the_bookkeeping_table(db: Db) -> None:
    assert db.run([]) == []

    assert "schema_migrations" in _tables(db)


def test_a_migration_and_its_record_commit_or_fail_together(db: Db) -> None:
    """
    A migration that succeeds but whose version row is rejected must not
    leave its schema change behind. A multi-statement string is one implicit
    transaction by itself, so the failing step has to be the separate row
    insert, and the migration has to be the kind that runs in a transaction.
    """
    db.conn.execute(
        "CREATE TABLE schema_migrations ("
        "version integer PRIMARY KEY, name text NOT NULL, "
        "checksum text NOT NULL CHECK (checksum <> ''), "
        "applied_at timestamptz NOT NULL DEFAULT now())"
    )
    unrecordable = Migration(
        version=1,
        name="0001_unrecordable.sql",
        sql="CREATE TABLE made (n integer);",
        checksum="",
        transactional=True,
    )

    with pytest.raises(MigrationError, match="0001_unrecordable.sql"):
        db.run([unrecordable])

    assert "made" not in _tables(db)
    assert _applied(db) == []


@pytest.mark.parametrize(
    ("sql", "fails"),
    [
        ("CREATE TABLE t (n integer);\n", False),
        ("SELECT 1/0;\n", True),
    ],
)
def test_the_lock_is_released_when_the_connection_stays_open(
    db: Db,
    tmp_path: Path,
    sql: str,
    fails: bool,
) -> None:
    """
    Closing a connection releases its advisory lock, so a run that ends by
    closing proves nothing about the explicit release. Here the connection
    outlives the run, and a second connection must be able to take the lock.
    """
    migrations = _load(tmp_path, {"0001_a.sql": sql})

    with psycopg.connect(db.url, autocommit=True, **db.connect_kwargs) as held:
        if fails:
            with pytest.raises(MigrationError):
                _apply_locked(held, migrations, db.lock_key, 5.0)
        else:
            _apply_locked(held, migrations, db.lock_key, 5.0)

        with psycopg.connect(db.url, autocommit=True) as other:
            row = other.execute(
                "SELECT pg_try_advisory_lock(%s::bigint)", (db.lock_key,)
            ).fetchone()

    assert row is not None
    assert row[0] is True
