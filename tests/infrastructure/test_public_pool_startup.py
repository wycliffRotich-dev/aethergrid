"""
ADR 0104, decision 6. The public pool waits for its first connection.

open_public_pool opens the pool and waits for one connection. When that
fails, whatever the reason, it closes the pool and raises one fixed message
that names the password file setting it was given. The message, its repr, its
chain and the log records hold no part of the URL, the password or the text
of the driver, which can echo either. A bad password or an unreachable
database then stops the app at start, and the first visitor does not find it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg_pool import PoolTimeout

from app.infrastructure.public_read import public_pool

ROLE = "aethergrid_public_app"
URL = f"postgresql://{ROLE}@db.example.org/demo"
SETTING = "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE"
OTHER_SETTING = "SOME_OTHER_SETTING"
PASSWORD = "startup-password-9c1e"
CANARY = "driver-canary-4d7a"
STARTUP_TIMEOUT_SECONDS = 5.0

ERRORS = [
    pytest.param(PoolTimeout(CANARY), id="pool-timeout"),
    pytest.param(psycopg.OperationalError(CANARY), id="driver-error"),
    pytest.param(RuntimeError(CANARY), id="runtime-error"),
    pytest.param(ValueError(CANARY), id="value-error"),
]


def _message(setting: str) -> str:
    return (
        "the public database pool could not open its first connection, "
        f"check the database URL and {setting}"
    )


class RecordingPool:
    """Stands in for ConnectionPool and remembers how it was used."""

    def __init__(
        self,
        conninfo: str,
        open_error: Exception | None = None,
        close_error: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        self.conninfo = conninfo
        self.kwargs = kwargs
        self.open_error = open_error
        self.close_error = close_error
        self.opened: list[dict[str, Any]] = []
        self.closed = 0

    def open(self, wait: bool = False, timeout: float = 30.0) -> None:
        self.opened.append({"wait": wait, "timeout": timeout})

        if self.open_error is not None:
            raise self.open_error

    def close(self) -> None:
        self.closed += 1

        if self.close_error is not None:
            raise self.close_error


class Pools:
    def __init__(self) -> None:
        self.made: list[RecordingPool] = []
        self.open_error: Exception | None = None
        self.close_error: Exception | None = None


@pytest.fixture
def pools(monkeypatch: pytest.MonkeyPatch) -> Pools:
    state = Pools()

    def factory(conninfo: str, **kwargs: Any) -> RecordingPool:
        pool = RecordingPool(
            conninfo,
            open_error=state.open_error,
            close_error=state.close_error,
            **kwargs,
        )
        state.made.append(pool)
        return pool

    monkeypatch.setattr(public_pool, "ConnectionPool", factory)

    return state


@pytest.fixture
def password_file(tmp_path: Path) -> str:
    secret = tmp_path / "pw"
    secret.write_text(PASSWORD)

    return str(secret)


def test_the_pool_is_opened_once_and_waits_for_a_connection(
    pools: Pools, password_file: str
) -> None:
    opened = public_pool.open_public_pool(URL, password_file, SETTING)

    assert pools.made == [opened]
    assert pools.made[0].opened == [
        {"wait": True, "timeout": STARTUP_TIMEOUT_SECONDS}
    ]
    assert pools.made[0].closed == 0


@pytest.mark.parametrize("error", ERRORS)
def test_a_failure_closes_the_pool_and_raises_one_fixed_message(
    error: Exception,
    pools: Pools,
    password_file: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    pools.open_error = error

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(RuntimeError) as err:
            public_pool.open_public_pool(URL, password_file, SETTING)

    assert str(err.value) == _message(SETTING)
    assert err.value.args == (_message(SETTING),)
    assert err.value.__cause__ is None
    assert err.value.__suppress_context__ is True
    assert pools.made[0].closed == 1

    for secret in (CANARY, PASSWORD, URL, "db.example.org"):
        assert secret not in repr(err.value)
        assert secret not in caplog.text


@pytest.mark.parametrize("setting", [SETTING, OTHER_SETTING])
def test_the_message_names_the_setting_that_was_given(
    setting: str, pools: Pools, password_file: str
) -> None:
    pools.open_error = PoolTimeout(CANARY)

    with pytest.raises(RuntimeError) as err:
        public_pool.open_public_pool(URL, password_file, setting)

    assert str(err.value) == _message(setting)
    assert "NEUROMESH" not in str(err.value)


def test_a_pool_that_cannot_close_still_gives_the_fixed_message(
    pools: Pools, password_file: str, caplog: pytest.LogCaptureFixture
) -> None:
    pools.open_error = PoolTimeout(CANARY)
    pools.close_error = RuntimeError(CANARY)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(RuntimeError) as err:
            public_pool.open_public_pool(URL, password_file, SETTING)

    assert str(err.value) == _message(SETTING)
    assert err.value.__cause__ is None
    assert err.value.__suppress_context__ is True
    assert pools.made[0].closed == 1
    assert CANARY not in repr(err.value)
    assert CANARY not in caplog.text
