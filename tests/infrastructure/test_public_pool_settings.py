"""
ADR 0102, decision 3, and ADR 0104, decision 5. The values of the public pool.

The pool has one connection at least and five at most, waits two seconds for
a connection, and commits each statement as it runs. Every connection starts
read only with a statement timeout of 2000 ms. These come from the function
and never from the URL. The connection keywords are exactly the password, the
autocommit flag and the options, so nothing else can steer where the pool
connects or how a session behaves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.infrastructure.public_read import public_pool

ROLE = "aethergrid_public_app"
URL = f"postgresql://{ROLE}@db.example.org/demo"
SETTING = "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE"

EXPECTED_OPTIONS = {
    "statement_timeout": "2000",
    "default_transaction_read_only": "on",
}


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
def pool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> RecordingPool:
    made: list[RecordingPool] = []

    def factory(conninfo: str, **kwargs: Any) -> RecordingPool:
        recording = RecordingPool(conninfo, **kwargs)
        made.append(recording)
        return recording

    monkeypatch.setattr(public_pool, "ConnectionPool", factory)
    secret = tmp_path / "pw"
    secret.write_text("a-password-for-the-tests\n")

    public_pool.open_public_pool(URL, str(secret), SETTING)

    assert len(made) == 1
    return made[0]


def test_the_pool_keeps_at_least_one_connection(pool: RecordingPool) -> None:
    assert pool.kwargs["min_size"] == 1


def test_the_pool_holds_at_most_five_connections(pool: RecordingPool) -> None:
    assert pool.kwargs["max_size"] == 5


def test_the_pool_waits_two_seconds_for_a_connection(pool: RecordingPool) -> None:
    assert pool.kwargs["timeout"] == 2.0


def test_every_connection_commits_each_statement_as_it_runs(
    pool: RecordingPool,
) -> None:
    assert pool.kwargs["kwargs"]["autocommit"] is True


def test_every_connection_starts_read_only_with_a_statement_timeout(
    pool: RecordingPool,
) -> None:
    words = pool.kwargs["kwargs"]["options"].split()

    assert words[0::2] == ["-c"] * (len(words) // 2)
    assert len(words) % 2 == 0
    assert dict(word.split("=", 1) for word in words[1::2]) == EXPECTED_OPTIONS
    assert len(words[1::2]) == len(EXPECTED_OPTIONS)


def test_the_connection_keywords_are_exactly_the_three_that_are_decided(
    pool: RecordingPool,
) -> None:
    assert set(pool.kwargs["kwargs"]) == {"password", "autocommit", "options"}
