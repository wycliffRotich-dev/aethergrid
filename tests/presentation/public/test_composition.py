"""
ADR 0102, decision 6. The second composition root reads the environment,
opens the public pool, and gives the app a lifespan that only closes the
pool. The pool is a fake here. The real pool is tested against a database
under ADR 0104.
"""

from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.presentation.public import composition
from tests.support.public_app import PUBLIC_PATHS

PASSWORD_SETTING = "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE"
URL = "postgresql://aethergrid_public_app@db.internal:5432/aethergrid"
PASSWORD_FILE = "/run/secrets/public_db_password"
ENVIRONMENT = {
    "AETHERGRID_PUBLIC_ALLOWED_ORIGIN": "https://demo.example.org",
    "AETHERGRID_PUBLIC_DATABASE_URL": URL,
    PASSWORD_SETTING: PASSWORD_FILE,
    "AETHERGRID_PUBLIC_TRUSTED_PROXY_HOPS": "1",
}


class FakePool:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class FakeOpen:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.pool = FakePool()
        self.error = error

    def __call__(
        self, database_url: str, password_file: str, password_file_setting: str
    ) -> FakePool:
        self.calls.append((database_url, password_file, password_file_setting))
        if self.error is not None:
            raise self.error
        return self.pool


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> FakeOpen:
    fake = FakeOpen()
    monkeypatch.setattr(composition, "open_public_pool", fake)
    return fake


def test_the_pool_is_opened_from_the_public_values(opened: FakeOpen) -> None:
    composition.create_app(ENVIRONMENT)

    assert opened.calls == [(URL, PASSWORD_FILE, PASSWORD_SETTING)]


def test_a_bad_setting_stops_construction_before_the_pool_opens(
    opened: FakeOpen,
) -> None:
    broken = {**ENVIRONMENT, "AETHERGRID_PUBLIC_ALLOWED_ORIGIN": "*"}

    with pytest.raises(ValueError, match="AETHERGRID_PUBLIC_ALLOWED_ORIGIN"):
        composition.create_app(broken)

    assert opened.calls == []


def test_a_pool_that_fails_to_open_stops_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = FakeOpen(error=RuntimeError("fixed message"))
    monkeypatch.setattr(composition, "open_public_pool", failing)

    with pytest.raises(RuntimeError, match="fixed message"):
        composition.create_app(ENVIRONMENT)


def test_the_pool_is_closed_once_and_only_when_the_app_stops(
    opened: FakeOpen,
) -> None:
    app = composition.create_app(ENVIRONMENT)

    assert opened.pool.closed == 0

    with TestClient(app) as client:
        for _ in range(3):
            assert client.get("/healthz").status_code == 200
        assert opened.pool.closed == 0
        assert len(opened.calls) == 1

    assert opened.pool.closed == 1


def test_the_composed_app_serves_the_health_route_and_the_seven_public_routes(
    opened: FakeOpen,
) -> None:
    app = composition.create_app(ENVIRONMENT)

    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}

    assert paths == PUBLIC_PATHS


def test_the_process_environment_is_the_default(
    opened: FakeOpen, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in ENVIRONMENT.items():
        monkeypatch.setenv(name, value)

    composition.create_app()

    assert opened.calls == [(URL, PASSWORD_FILE, PASSWORD_SETTING)]


def test_a_failure_after_the_pool_opens_closes_the_pool(
    opened: FakeOpen, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("app construction failed")

    monkeypatch.setattr(composition, "create_public_app", broken)

    with pytest.raises(RuntimeError, match="app construction failed"):
        composition.create_app(ENVIRONMENT)

    assert opened.pool.closed == 1


def test_importing_the_entry_point_opens_nothing(opened: FakeOpen) -> None:
    sys.modules.pop("app.public_main", None)

    module = importlib.import_module("app.public_main")

    assert opened.calls == []
    assert module.create_app is composition.create_app
    assert not hasattr(module, "app")


class FailingClosePool(FakePool):
    def close(self) -> None:
        super().close()
        raise RuntimeError("close failed")


def test_a_pool_that_fails_to_close_at_shutdown_is_not_hidden(
    opened: FakeOpen,
) -> None:
    opened.pool = FailingClosePool()
    app = composition.create_app(ENVIRONMENT)

    with pytest.raises(RuntimeError, match="close failed"):
        with TestClient(app):
            pass

    assert opened.pool.closed == 1


def test_a_close_failure_does_not_replace_the_construction_error(
    opened: FakeOpen, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened.pool = FailingClosePool()

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("app construction failed")

    monkeypatch.setattr(composition, "create_public_app", broken)

    with pytest.raises(RuntimeError, match="app construction failed"):
        composition.create_app(ENVIRONMENT)

    assert opened.pool.closed == 1
