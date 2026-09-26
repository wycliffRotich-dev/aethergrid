from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.presentation.api as api_module
from app.presentation.api import app


def test_lifespan_waits_for_pool_before_completing_startup(
    monkeypatch,
) -> None:
    """
    ADR 0046: the official Postgres image's two-phase startup
    lets pg_isready report healthy against a temporary initdb
    instance before the real instance is up. Without blocking
    on pool readiness, the app could report itself started, and
    accept requests including Docker's own healthcheck, during
    that gap.

    lifespan() must call pool.wait() before yielding control to
    Uvicorn, so "Application startup complete" only becomes true
    once the pool has a confirmed, live connection.
    """
    fake_pool = MagicMock()
    monkeypatch.setattr(
        api_module,
        "get_connection_pool",
        lambda: fake_pool,
    )

    with TestClient(app):
        pass

    fake_pool.wait.assert_called_once_with(timeout=30.0)


def test_lifespan_fails_startup_if_pool_never_becomes_ready(
    monkeypatch,
) -> None:
    """
    If the pool never becomes ready within its timeout, the app
    must fail to start rather than silently coming up unready.
    lifespan() has no try/except around pool.wait(), so whatever
    it raises should propagate through TestClient's own startup
    and prevent the app from ever reporting itself started.
    """
    fake_pool = MagicMock()
    fake_pool.wait.side_effect = RuntimeError(
        "pool never became ready"
    )
    monkeypatch.setattr(
        api_module,
        "get_connection_pool",
        lambda: fake_pool,
    )

    with pytest.raises(RuntimeError):
        with TestClient(app):
            pass
