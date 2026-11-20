"""
ADR 0104, decisions 2, 3 and 6. The URL that the public pool accepts.

The URL is parsed the way libpq parses it and only listed keys pass. Every
refusal raises one fixed message that holds no part of the URL, comes before
the password file is read, and never touches the pool. The refused forms are
paired with accepted forms that reach the pool, so a check that refused
everything would fail here too.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from app.infrastructure.public_read import public_pool

ROLE = "aethergrid_public_app"
SETTING = "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE"
CANARY = "canary-7f3a91"
REFUSAL = "the database URL of the public pool is not accepted"

ACCEPTED = [
    pytest.param(f"postgresql://{ROLE}@db.example.org/demo", id="plain"),
    pytest.param(f"postgresql://{ROLE}@db.example.org:5432/demo", id="with-a-port"),
    pytest.param(
        f"postgres://{ROLE}@db.example.org/demo?sslmode=require",
        id="postgres-scheme-and-sslmode",
    ),
    pytest.param(
        f"postgresql://{ROLE}@db.example.org/demo"
        "?sslmode=verify-full&sslrootcert=/etc/ssl/ca.pem",
        id="sslmode-and-root-certificate",
    ),
    pytest.param(
        f"postgresql://db.example.org/demo?user={ROLE}",
        id="the-app-role-written-in-the-query",
    ),
]

REFUSED = [
    pytest.param(f"postgresql://{ROLE}:{CANARY}@h/demo", id="password-in-the-user-part"),
    pytest.param(
        f"postgresql://{ROLE}@h/demo?password={CANARY}", id="password-in-the-query"
    ),
    pytest.param(
        f"postgresql://{ROLE}@h/demo?pass%77ord={CANARY}",
        id="password-key-written-with-an-escape",
    ),
    pytest.param(
        f"postgresql://{ROLE}@h/demo#?password={CANARY}",
        id="password-after-a-hash-sign",
    ),
    pytest.param(
        f"postgresql://{ROLE}@h/demo?Password={CANARY}",
        id="key-spelled-with-a-capital",
    ),
    pytest.param(f"postgresql://{ROLE}@h/demo?passfile=/tmp/{CANARY}", id="passfile"),
    pytest.param(f"postgresql://{ROLE}@h/demo?service={CANARY}", id="service"),
    pytest.param(
        f"postgresql://{ROLE}@h/demo?options=-c%20search_path%3D{CANARY}",
        id="options",
    ),
    pytest.param(
        f"postgresql://{ROLE}@h/demo?application_name={CANARY}",
        id="a-key-that-is-not-listed",
    ),
    pytest.param(f"postgresql://{ROLE}@h/demo#", id="hash-sign-in-the-database-name"),
    pytest.param("postgresql://postgres@h/demo", id="another-user"),
    pytest.param(
        f"postgresql://{ROLE}@h/demo?user=postgres", id="user-replaced-in-the-query"
    ),
    pytest.param("postgresql://h/demo", id="no-user"),
    pytest.param(
        f"host=h user={ROLE} password={CANARY} dbname=demo",
        id="keyword-form-with-a-password",
    ),
    pytest.param(
        f"host=h user={ROLE} dbname=demo",
        id="keyword-form-with-listed-keys-only",
    ),
    pytest.param("", id="empty"),
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


@pytest.fixture
def password_file(tmp_path: Path) -> str:
    secret = tmp_path / "pw"
    secret.write_text("a-password-for-the-tests\n")

    return str(secret)


@pytest.mark.parametrize("url", ACCEPTED)
def test_an_accepted_url_reaches_the_pool(
    url: str, pools: list[RecordingPool], password_file: str
) -> None:
    opened = public_pool.open_public_pool(url, password_file, SETTING)

    assert pools == [opened]


@pytest.mark.parametrize("url", REFUSED)
def test_a_refused_url_raises_one_fixed_message_and_nothing_else_happens(
    url: str,
    pools: list[RecordingPool],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    missing = tmp_path / "no-such-file"

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ValueError) as err:
            public_pool.open_public_pool(url, str(missing), SETTING)

    assert str(err.value) == REFUSAL
    assert err.value.args == (REFUSAL,)
    assert err.value.__cause__ is None
    assert err.value.__suppress_context__ is True
    assert pools == []
    assert CANARY not in repr(err.value)
    assert CANARY not in caplog.text
    assert "NEUROMESH" not in str(err.value)
