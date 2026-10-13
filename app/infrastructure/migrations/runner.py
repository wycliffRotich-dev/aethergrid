"""Versioned SQL migrations (ADR 0071).

Migrations are files named NNNN_name.sql in one directory. The version
is the four digit prefix, versions start at 0001 and have no gaps, and
the checksum is the SHA-256 of the file bytes.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

NO_TRANSACTION_MARKER = "-- migration: no-transaction"

# The advisory lock key held while migrations run. Advisory locks are per
# database, so every runner against one database must use the same key.
# The default is the ASCII bytes of "nm_migra".
DEFAULT_LOCK_KEY = int.from_bytes(b"nm_migra", "big")
DEFAULT_LOCK_TIMEOUT_SECONDS = 60.0

_FILE_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class MigrationError(Exception):
    """A migration set is invalid, or a database cannot be brought to it."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str
    transactional: bool


def load_migrations(directory: Path) -> list[Migration]:
    """
    Read every NNNN_name.sql file in directory, in version order.

    Raises MigrationError when the directory does not exist, when a
    .sql file name does not match NNNN_name.sql (lowercase letters,
    digits and underscores in the name), when a version appears twice,
    when versions do not run 0001, 0002, ... without a gap, or when a
    file is not valid UTF-8. Files that do not end in .sql are ignored.

    A migration is transactional unless its first line is exactly
    NO_TRANSACTION_MARKER. The marker is read from the first line only,
    and a trailing carriage return on that line is ignored.
    """
    if not directory.is_dir():
        raise MigrationError(f"migrations directory does not exist: {directory}")

    found: dict[int, Migration] = {}

    for path in sorted(directory.iterdir()):
        if path.suffix != ".sql":
            continue

        match = _FILE_NAME.match(path.name)
        if match is None:
            raise MigrationError(
                f"{path.name} does not match NNNN_name.sql "
                "(four digits, then lowercase letters, digits and underscores)"
            )

        version = int(match.group(1))
        if version in found:
            raise MigrationError(
                f"version {version:04d} appears twice: "
                f"{found[version].name} and {path.name}"
            )

        data = path.read_bytes()
        try:
            sql = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise MigrationError(f"{path.name} is not valid UTF-8") from error

        first_line = sql.split("\n", 1)[0].rstrip("\r")
        found[version] = Migration(
            version=version,
            name=path.name,
            sql=sql,
            checksum=hashlib.sha256(data).hexdigest(),
            transactional=first_line != NO_TRANSACTION_MARKER,
        )

    for expected, version in enumerate(sorted(found), start=1):
        if version != expected:
            raise MigrationError(
                f"missing migration {expected:04d}: versions must run "
                "from 0001 without a gap"
            )

    return [found[version] for version in sorted(found)]


def apply_migrations(
    conninfo: str,
    migrations: Sequence[Migration],
    *,
    connect_kwargs: Mapping[str, Any] | None = None,
    lock_key: int = DEFAULT_LOCK_KEY,
    lock_timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
) -> list[int]:
    """
    Bring the database at conninfo up to the given migrations and
    return the versions applied by this call, in order.

    Opens its own connection and holds a Postgres advisory lock on
    lock_key for the whole run, so runners against one database
    serialize. A runner that cannot take the lock within
    lock_timeout_seconds raises MigrationError. The lock belongs to
    the connection, so it is released when the run ends, however it
    ends. connect_kwargs go to psycopg.connect (a password, or
    options such as a search_path).

    Creates schema_migrations (version integer primary key, name
    text, checksum text, applied_at timestamptz default now()) if it
    does not exist, in the first schema on the search path. Then:

    - every recorded version must have a file with the same
      checksum, otherwise MigrationError;
    - the recorded versions must be 1..N with no hole, otherwise
      MigrationError;
    - each missing migration is applied in order. A transactional
      migration runs in one transaction together with its
      schema_migrations row. A no-transaction migration runs as
      written and its row is written after it succeeds.

    A migration that fails raises MigrationError naming its file,
    with the database error as the cause. Earlier migrations stay
    applied and later ones are not attempted.
    """
    kwargs = dict(connect_kwargs or {})
    kwargs["autocommit"] = True

    with psycopg.connect(conninfo, **kwargs) as conn:
        return _apply_locked(conn, migrations, lock_key, lock_timeout_seconds)


def _apply_locked(
    conn: psycopg.Connection,
    migrations: Sequence[Migration],
    lock_key: int,
    lock_timeout_seconds: float,
) -> list[int]:
    """
    Take the advisory lock, apply the migrations, and release the lock
    explicitly however the run ends. The lock belongs to the connection,
    so closing it would release the lock too. The explicit release is for
    a connection that outlives the run, and the runner must connect to
    Postgres directly, because session level locks do not survive a
    transaction mode pooler.
    """
    _take_lock(conn, lock_key, lock_timeout_seconds)
    try:
        return _apply(conn, migrations)
    finally:
        _release_lock(conn, lock_key)


def _release_lock(
    conn: psycopg.Connection,
    lock_key: int,
) -> None:
    try:
        conn.execute("SELECT pg_advisory_unlock(%s::bigint)", (lock_key,))
    except psycopg.Error:
        # A broken connection drops its session locks when it closes, and a
        # failed unlock must not hide the error that ended the run.
        pass


def _take_lock(
    conn: psycopg.Connection,
    lock_key: int,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        row = conn.execute(
            "SELECT pg_try_advisory_lock(%s::bigint)", (lock_key,)
        ).fetchone()
        if row is not None and row[0]:
            return
        if time.monotonic() >= deadline:
            raise MigrationError(
                f"could not take the migration lock within {timeout_seconds} seconds; "
                "another runner holds it"
            )
        time.sleep(0.05)


def _apply(conn: psycopg.Connection, migrations: Sequence[Migration]) -> list[int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version integer PRIMARY KEY, "
        "name text NOT NULL, "
        "checksum text NOT NULL, "
        "applied_at timestamptz NOT NULL DEFAULT now())"
    )

    by_version = {m.version: m for m in migrations}
    recorded = conn.execute(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()

    for expected, (version, name, checksum) in enumerate(recorded, start=1):
        if version != expected:
            raise MigrationError(
                f"the applied history has a hole: migration {expected:04d} is not "
                f"recorded but {version:04d} is"
            )
        known = by_version.get(version)
        if known is None:
            raise MigrationError(
                f"migration {version:04d} ({name}) is recorded as applied but has "
                "no file in the migration set"
            )
        if known.checksum != checksum:
            raise MigrationError(
                f"checksum mismatch for {known.name}: the file changed after "
                "it was applied"
            )

    applied: list[int] = []
    for migration in migrations:
        if migration.version <= len(recorded):
            continue
        try:
            _run_one(conn, migration)
        except psycopg.Error as error:
            raise MigrationError(f"{migration.name} failed: {error}") from error
        applied.append(migration.version)
    return applied


def _record(conn: psycopg.Connection, migration: Migration) -> None:
    conn.execute(
        "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
        (migration.version, migration.name, migration.checksum),
    )


def _run_one(conn: psycopg.Connection, migration: Migration) -> None:
    if not migration.transactional:
        conn.execute(migration.sql)
        _record(conn, migration)
        return

    with conn.transaction():
        conn.execute(migration.sql)
        _record(conn, migration)
