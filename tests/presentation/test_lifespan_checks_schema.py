from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.presentation.api as api_module
from app.infrastructure.migrations.runner import MigrationError
from app.presentation.api import app


@pytest.fixture
def startup(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Record the order of startup steps and what the check was given."""
    order: list[str] = []
    seen: list[object] = []
    outcome: dict = {"result": ()}

    pool = MagicMock()
    pool.wait.side_effect = lambda **_: order.append("wait")
    monkeypatch.setattr(api_module, "get_connection_pool", lambda: pool)

    def fake_check(given: object) -> tuple[int, ...]:
        order.append("check")
        seen.append(given)
        if isinstance(outcome["result"], Exception):
            raise outcome["result"]
        return outcome["result"]

    monkeypatch.setattr(api_module, "check_database_schema", fake_check)

    def fake_loop():
        order.append("loop")

        async def idle() -> None:
            return None

        return idle()

    monkeypatch.setattr(api_module, "_run_cluster_loop", fake_loop)
    return {"order": order, "seen": seen, "pool": pool, "outcome": outcome}


def test_the_schema_is_checked_after_the_pool_is_ready_and_before_the_loop(
    startup: dict,
) -> None:
    with TestClient(app):
        pass

    assert startup["order"] == ["wait", "check", "loop"]


def test_the_check_receives_the_pool_the_lifespan_waited_on(startup: dict) -> None:
    with TestClient(app):
        pass

    assert startup["seen"] == [startup["pool"]]


def test_a_refused_schema_stops_startup_before_the_loop(startup: dict) -> None:
    startup["outcome"]["result"] = MigrationError("the database is behind")

    with pytest.raises(MigrationError, match="behind"):
        with TestClient(app):
            pass

    assert startup["order"] == ["wait", "check"]


def test_an_ahead_database_is_logged_and_startup_continues(
    startup: dict,
    caplog: pytest.LogCaptureFixture,
) -> None:
    startup["outcome"]["result"] = (2, 3)

    with caplog.at_level(logging.WARNING, logger=api_module.logger.name):
        with TestClient(app):
            pass

    assert "0002, 0003" in caplog.text
    assert startup["order"] == ["wait", "check", "loop"]
