"""
The password file reader shared by the private and the public app
(ADR 0102, decision 4). It reads and validates one file and names the
setting it was given in every message, never a setting of its own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.database_credentials import read_password_file

PUBLIC_SETTING = "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE"


def test_reads_the_password(tmp_path: Path) -> None:
    secret = tmp_path / "pw"
    secret.write_text("s3cret-value")

    assert read_password_file(str(secret), PUBLIC_SETTING) == "s3cret-value"


def test_strips_exactly_one_trailing_newline(tmp_path: Path) -> None:
    secret = tmp_path / "pw"
    secret.write_text("abc\n\n")

    assert read_password_file(str(secret), PUBLIC_SETTING) == "abc\n"


def test_keeps_other_whitespace(tmp_path: Path) -> None:
    secret = tmp_path / "pw"
    secret.write_text(" a b \n")

    assert read_password_file(str(secret), PUBLIC_SETTING) == " a b "


def test_a_missing_file_names_the_given_setting_and_the_path(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "nope"

    with pytest.raises(RuntimeError) as err:
        read_password_file(str(missing), PUBLIC_SETTING)

    assert str(err.value) == (
        f"{PUBLIC_SETTING} points at '{missing}', "
        "which could not be read: No such file or directory."
    )
    assert err.value.__suppress_context__ is True


def test_a_directory_is_reported_not_raised_as_an_os_error(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError) as err:
        read_password_file(str(tmp_path), PUBLIC_SETTING)

    assert str(err.value).startswith(
        f"{PUBLIC_SETTING} points at '{tmp_path}', which could not be read:"
    )


def test_an_empty_file_is_rejected_and_names_the_given_setting(
    tmp_path: Path,
) -> None:
    secret = tmp_path / "pw"
    secret.write_text("\n")

    with pytest.raises(RuntimeError) as err:
        read_password_file(str(secret), PUBLIC_SETTING)

    assert str(err.value) == (
        f"{PUBLIC_SETTING} points at '{secret}', which is empty."
    )


@pytest.mark.parametrize("kind", ["missing", "empty", "directory"])
def test_no_message_names_a_private_setting(
    tmp_path: Path, kind: str
) -> None:
    target = tmp_path / "pw"
    if kind == "empty":
        target.write_text("")
    if kind == "directory":
        target = tmp_path

    with pytest.raises(RuntimeError) as err:
        read_password_file(str(target), PUBLIC_SETTING)

    assert "NEUROMESH" not in str(err.value)
