from __future__ import annotations

import pytest

from app.infrastructure.database_credentials import (
    resolve_database_password,
)

URL_NO_PASSWORD = "postgresql://neuromesh@postgres:5432/neuromesh"
URL_WITH_PASSWORD = "postgresql://neuromesh:secret@postgres:5432/neuromesh"


def test_returns_none_when_no_file_is_configured() -> None:
    assert resolve_database_password(URL_WITH_PASSWORD, {}) is None


def test_reads_the_password_from_the_file(tmp_path) -> None:
    secret = tmp_path / "pw"
    secret.write_text("s3cret-value")
    env = {"NEUROMESH_DATABASE_PASSWORD_FILE": str(secret)}
    assert resolve_database_password(URL_NO_PASSWORD, env) == "s3cret-value"


def test_strips_exactly_one_trailing_newline(tmp_path) -> None:
    secret = tmp_path / "pw"
    secret.write_text("abc\n")
    env = {"NEUROMESH_DATABASE_PASSWORD_FILE": str(secret)}
    assert resolve_database_password(URL_NO_PASSWORD, env) == "abc"


def test_keeps_other_whitespace(tmp_path) -> None:
    secret = tmp_path / "pw"
    secret.write_text(" a b \n")
    env = {"NEUROMESH_DATABASE_PASSWORD_FILE": str(secret)}
    assert resolve_database_password(URL_NO_PASSWORD, env) == " a b "


def test_rejects_a_password_in_both_places(tmp_path) -> None:
    secret = tmp_path / "pw"
    secret.write_text("abc")
    env = {"NEUROMESH_DATABASE_PASSWORD_FILE": str(secret)}
    with pytest.raises(RuntimeError) as err:
        resolve_database_password(URL_WITH_PASSWORD, env)
    message = str(err.value)
    assert "NEUROMESH_DATABASE_URL" in message
    assert "NEUROMESH_DATABASE_PASSWORD_FILE" in message
    assert "secret" not in message


def test_missing_file_names_the_path(tmp_path) -> None:
    missing = tmp_path / "nope"
    env = {"NEUROMESH_DATABASE_PASSWORD_FILE": str(missing)}
    with pytest.raises(RuntimeError) as err:
        resolve_database_password(URL_NO_PASSWORD, env)
    assert str(missing) in str(err.value)


def test_empty_file_is_rejected_without_leaking(tmp_path) -> None:
    secret = tmp_path / "pw"
    secret.write_text("\n")
    env = {"NEUROMESH_DATABASE_PASSWORD_FILE": str(secret)}
    with pytest.raises(RuntimeError) as err:
        resolve_database_password(URL_NO_PASSWORD, env)
    assert str(secret) in str(err.value)


def test_the_missing_file_message_is_exactly_this(tmp_path) -> None:
    missing = tmp_path / "nope"
    env = {"NEUROMESH_DATABASE_PASSWORD_FILE": str(missing)}
    with pytest.raises(RuntimeError) as err:
        resolve_database_password(URL_NO_PASSWORD, env)
    assert str(err.value) == (
        f"NEUROMESH_DATABASE_PASSWORD_FILE points at '{missing}', "
        "which could not be read: No such file or directory."
    )
    assert err.value.__cause__ is None
    assert err.value.__suppress_context__ is True


def test_the_empty_file_message_is_exactly_this(tmp_path) -> None:
    secret = tmp_path / "pw"
    secret.write_text("")
    env = {"NEUROMESH_DATABASE_PASSWORD_FILE": str(secret)}
    with pytest.raises(RuntimeError) as err:
        resolve_database_password(URL_NO_PASSWORD, env)
    assert str(err.value) == (
        f"NEUROMESH_DATABASE_PASSWORD_FILE points at '{secret}', "
        "which is empty."
    )


def test_the_two_credentials_message_is_exactly_this(tmp_path) -> None:
    secret = tmp_path / "pw"
    secret.write_text("abc")
    env = {"NEUROMESH_DATABASE_PASSWORD_FILE": str(secret)}
    with pytest.raises(RuntimeError) as err:
        resolve_database_password(URL_WITH_PASSWORD, env)
    assert str(err.value) == (
        "NEUROMESH_DATABASE_URL already contains a password and "
        "NEUROMESH_DATABASE_PASSWORD_FILE is also set. Use one or the "
        "other: remove the password from the URL to read it from the file."
    )
