from __future__ import annotations

import contextlib

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

import app.presentation.dependencies as dependencies
from app.presentation.api import HEALTH_CHECK_TIMEOUT_SECONDS, app


class _Connection:
    def __init__(self, error: Exception | None = None) -> None:
        self.queries: list[str] = []
        self._error = error

    def execute(self, query: str) -> None:
        self.queries.append(query)
        if self._error is not None:
            raise self._error


class _Pool:
    def __init__(
        self,
        connection: _Connection | None = None,
        connect_error: Exception | None = None,
    ) -> None:
        self.timeouts: list[float | None] = []
        self._connection = connection
        self._connect_error = connect_error

    def connection(self, timeout: float | None = None):
        self.timeouts.append(timeout)
        if self._connect_error is not None:
            raise self._connect_error
        return contextlib.nullcontext(self._connection)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _use_pool(monkeypatch: pytest.MonkeyPatch, pool: object) -> None:
    monkeypatch.setattr(dependencies, "_connection_pool", pool)


def test_health_is_healthy_when_there_is_no_pool(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_pool(monkeypatch, None)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_health_asks_the_pool_one_question_on_its_own_short_timeout(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _Connection()
    pool = _Pool(connection=connection)
    _use_pool(monkeypatch, pool)

    response = client.get("/health")

    assert response.status_code == 200
    assert connection.queries == ["SELECT 1"]
    assert pool.timeouts == [HEALTH_CHECK_TIMEOUT_SECONDS]
    # ADR 0046: far shorter than the pool's 30 second default.
    assert HEALTH_CHECK_TIMEOUT_SECONDS < 30.0


@pytest.mark.parametrize(
    ("pool", "error_name"),
    [
        (
            _Pool(connect_error=PoolTimeout("secret detail")),
            "PoolTimeout",
        ),
        (
            _Pool(
                connection=_Connection(
                    error=psycopg.OperationalError("secret detail")
                )
            ),
            "OperationalError",
        ),
    ],
    ids=["no_connection_in_time", "query_fails"],
)
def test_health_is_503_with_only_the_exception_class_when_the_database_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    pool: _Pool,
    error_name: str,
) -> None:
    _use_pool(monkeypatch, pool)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "error": error_name}
    assert "secret detail" not in response.text
