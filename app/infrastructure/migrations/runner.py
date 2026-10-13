"""Versioned SQL migrations (ADR 0071).

Migrations are files named NNNN_name.sql in one directory. The version
is the four digit prefix, versions start at 0001 and have no gaps, and
the checksum is the SHA-256 of the file bytes.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

NO_TRANSACTION_MARKER = "-- migration: no-transaction"

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
