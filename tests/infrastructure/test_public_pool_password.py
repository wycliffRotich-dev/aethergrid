"""
ADR 0104, decision 4. The password of the public pool.

open_public_pool reads the password file with read_password_file and the
setting name it was given, and hands the password to the pool as a
connection keyword. The password is never part of the URL, so it is not
escaped, logged or repeated in a message. A file that cannot be read stops
the function before a pool exists, with the message of read_password_file.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from app.infrastructure.public_read import public_pool

ROLE = "aethergrid_public_app"
URL = f"postgresql://{ROLE}@db.example.org/demo"
SETTING = "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE"
OTHER_SETTING = "SOME_OTHER_SETTING"

PASSWORDS = [
    pytest.param("plain-value-1", "plain-value-1", id="plain"),
    pytest.param("with-newline-2\n", "with-newline-2", id="one-trailing-newline"),
    pytest.param(
        "p@ss:w/rd#?%&=3", "p@ss:w/rd#?%&=3", id="characters-that-a-url-escapes"
    ),
    pytest.param(" spaced value 4 ", " spaced value 4 ", id="spaces-are-kept"),
]


class RecordingPool:
    """Stands in for ConnectionPool and remembers what it was given."""

    def __init__(self, conninfo: str, **kwargs: Any) -> None:
        self.conninfo = conninfo
        self.kwargs = kwargs

    def open(self, wait: bool = False, timeout: float = 30.0) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.fixture
def pools(monkeypatch: pytest.MonkeyPatch) -> list[RecordingPool]:
    made: list[RecordingPool] = []

    def factory(conninfo: str, **kwargs: Any) -> RecordingPool:
        pool = RecordingPool(conninfo, **kwargs)
        made.append(pool)
        return pool

    monkeypatch.setattr(public_pool, "ConnectionPool", factory)

    return made


def _file(tmp_path: Path, content: str) -> str:
    secret = tmp_path / "pw"
    secret.write_text(content)

    return str(secret)


@pytest.mark.parametrize(("content", "password"), PASSWORDS)
def test_the_password_reaches_the_pool_as_a_keyword_and_not_in_the_url(
    content: str, password: str, pools: list[RecordingPool], tmp_path: Path
) -> None:
    public_pool.open_public_pool(URL, _file(tmp_path, content), SETTING)

    assert len(pools) == 1
    assert pools[0].kwargs["kwargs"]["password"] == password
    assert pools[0].conninfo == URL
    assert password not in pools[0].conninfo


@pytest.mark.parametrize("setting", [SETTING, OTHER_SETTING])
def test_a_missing_file_stops_the_function_and_names_the_given_setting(
    setting: str, pools: list[RecordingPool], tmp_path: Path
) -> None:
    missing = tmp_path / "no-such-file"

    with pytest.raises(RuntimeError) as err:
        public_pool.open_public_pool(URL, str(missing), setting)

    assert str(err.value) == (
        f"{setting} points at '{missing}', "
        "which could not be read: No such file or directory."
    )
    assert err.value.__cause__ is None
    assert err.value.__suppress_context__ is True
    assert "NEUROMESH" not in str(err.value)
    assert pools == []


@pytest.mark.parametrize("content", ["", "\n"])
def test_an_empty_file_stops_the_function_before_a_pool_exists(
    content: str, pools: list[RecordingPool], tmp_path: Path
) -> None:
    secret = _file(tmp_path, content)

    with pytest.raises(RuntimeError) as err:
        public_pool.open_public_pool(URL, secret, SETTING)

    assert str(err.value) == f"{SETTING} points at '{secret}', which is empty."
    assert "NEUROMESH" not in str(err.value)
    assert pools == []


def test_the_password_is_never_logged(
    pools: list[RecordingPool], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    password = "log-canary-5b2d"

    with caplog.at_level(logging.DEBUG):
        public_pool.open_public_pool(URL, _file(tmp_path, password), SETTING)

    assert pools[0].kwargs["kwargs"]["password"] == password
    assert password not in caplog.text
