"""
Liveness must not depend on the database. The connection pool
dependency is overridden to raise, so if /livez ever resolves it
(directly or through a new dependency), this test fails.
"""

from fastapi.testclient import TestClient

from app.presentation.api import app
from app.presentation.dependencies import get_connection_pool


def _pool_that_must_not_be_resolved():
    raise RuntimeError("liveness must never resolve the connection pool")


def test_liveness_does_not_depend_on_the_connection_pool() -> None:
    app.dependency_overrides[get_connection_pool] = (
        _pool_that_must_not_be_resolved
    )

    try:
        response = TestClient(app).get("/livez")
    finally:
        app.dependency_overrides.pop(get_connection_pool, None)

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
