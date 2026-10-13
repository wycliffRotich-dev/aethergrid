from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from app.infrastructure.migrations.runner import (
    NO_TRANSACTION_MARKER,
    MigrationError,
    load_migrations,
)


def _write(directory: Path, name: str, text: str = "SELECT 1;\n") -> None:
    (directory / name).write_bytes(text.encode("utf-8"))


def test_loads_migrations_in_version_order(tmp_path: Path) -> None:
    _write(tmp_path, "0002_second.sql")
    _write(tmp_path, "0001_first.sql")

    migrations = load_migrations(tmp_path)

    assert [m.version for m in migrations] == [1, 2]
    assert [m.name for m in migrations] == ["0001_first.sql", "0002_second.sql"]


def test_checksum_is_the_sha256_of_the_file_bytes(tmp_path: Path) -> None:
    _write(tmp_path, "0001_first.sql", "SELECT 1;\n")

    (migration,) = load_migrations(tmp_path)

    assert migration.checksum == hashlib.sha256(b"SELECT 1;\n").hexdigest()
    assert migration.sql == "SELECT 1;\n"


def test_a_migration_is_transactional_by_default(tmp_path: Path) -> None:
    _write(tmp_path, "0001_first.sql")

    (migration,) = load_migrations(tmp_path)

    assert migration.transactional is True


def test_the_first_line_marker_makes_a_migration_non_transactional(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "0001_first.sql", f"{NO_TRANSACTION_MARKER}\nSELECT 1;\n")

    (migration,) = load_migrations(tmp_path)

    assert migration.transactional is False


def test_the_marker_is_recognised_with_windows_line_endings(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "0001_first.sql",
        f"{NO_TRANSACTION_MARKER}\r\nSELECT 1;\r\n",
    )

    (migration,) = load_migrations(tmp_path)

    assert migration.transactional is False


def test_the_marker_is_read_only_from_the_first_line(tmp_path: Path) -> None:
    _write(tmp_path, "0001_first.sql", f"SELECT 1;\n{NO_TRANSACTION_MARKER}\n")

    (migration,) = load_migrations(tmp_path)

    assert migration.transactional is True


@pytest.mark.parametrize(
    "bad_name",
    [
        "1_first.sql",
        "0001-first.sql",
        "0001_First.sql",
        "baseline.sql",
        "0001_.sql",
    ],
)
def test_rejects_a_file_name_that_does_not_match_the_pattern(
    tmp_path: Path,
    bad_name: str,
) -> None:
    _write(tmp_path, bad_name)

    with pytest.raises(MigrationError, match=re.escape(bad_name)):
        load_migrations(tmp_path)


def test_rejects_a_duplicate_version(tmp_path: Path) -> None:
    _write(tmp_path, "0001_a.sql")
    _write(tmp_path, "0001_b.sql")

    with pytest.raises(MigrationError, match="0001"):
        load_migrations(tmp_path)


def test_rejects_a_gap_in_versions(tmp_path: Path) -> None:
    _write(tmp_path, "0001_a.sql")
    _write(tmp_path, "0003_c.sql")

    with pytest.raises(MigrationError, match="0002"):
        load_migrations(tmp_path)


def test_versions_must_start_at_one(tmp_path: Path) -> None:
    _write(tmp_path, "0002_b.sql")

    with pytest.raises(MigrationError, match="0001"):
        load_migrations(tmp_path)


def test_a_missing_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="does not exist"):
        load_migrations(tmp_path / "missing")


def test_an_empty_directory_loads_nothing(tmp_path: Path) -> None:
    assert load_migrations(tmp_path) == []


def test_ignores_files_that_are_not_sql(tmp_path: Path) -> None:
    _write(tmp_path, "README.md", "notes")
    _write(tmp_path, "0001_first.sql")

    assert [m.version for m in load_migrations(tmp_path)] == [1]


def test_rejects_a_file_that_is_not_utf8(tmp_path: Path) -> None:
    (tmp_path / "0001_first.sql").write_bytes(b"\xff\xfe\x00")

    with pytest.raises(MigrationError, match="UTF-8"):
        load_migrations(tmp_path)
