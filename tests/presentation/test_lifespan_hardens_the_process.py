"""
ADR 0095. The API process holds the database credentials, and in-process
execution runs a job's command below it. It must close its own /proc entry
before it starts anything else.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.presentation.api as api_module
from app.presentation.api import app


def test_the_process_is_hardened_before_anything_else_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    pool = MagicMock()
    pool.wait.side_effect = lambda **_: order.append("wait")
    monkeypatch.setattr(api_module, "get_connection_pool", lambda: pool)

    def fake_check(given: object) -> tuple[int, ...]:
        order.append("check")
        return ()

    monkeypatch.setattr(api_module, "check_database_schema", fake_check)

    def fake_loop():
        order.append("loop")

        async def idle() -> None:
            return None

        return idle()

    monkeypatch.setattr(api_module, "_run_cluster_loop", fake_loop)
    monkeypatch.setattr(
        api_module,
        "make_unreadable_through_proc",
        lambda: order.append("harden"),
        raising=False,
    )

    with TestClient(app):
        pass

    assert order == ["harden", "wait", "check", "loop"]
