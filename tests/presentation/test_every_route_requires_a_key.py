"""
Every operation except the exempt probes must answer 401 when no key is
sent (ADR 0015, ADR 0064 point 10). The registry classifies routes and the
routers carry the key dependency, but this test makes the request.

The presentation conftest overrides require_api_key and require_rate_limit
for every test, which would turn each answer into a 200. This test removes
both overrides for its own duration and restores them afterwards.

Limit: it sends an empty JSON body, so a route that validated the body
before the key would show a 422 here, and that is reported as a failure.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.presentation.api import app
from app.presentation.auth import require_api_key, require_rate_limit
from tests.presentation.test_route_tenancy_registry import EXEMPT, REGISTRY

METHODS = {"get", "post", "put", "patch", "delete"}
DUMMY = "00000000-0000-0000-0000-000000000000"
MIN_OPERATIONS = 20


def _operations() -> list[tuple[str, str]]:
    return [
        (method.upper(), path)
        for path, ops in app.openapi()["paths"].items()
        for method in ops
        if method in METHODS
    ]


def _url(path: str) -> str:
    while "{" in path:
        start = path.index("{")
        path = path[:start] + DUMMY + path[path.index("}", start) + 1 :]
    return path


@pytest.fixture()
def no_overrides() -> Iterator[None]:
    saved = {
        dep: app.dependency_overrides.pop(dep)
        for dep in (require_api_key, require_rate_limit)
        if dep in app.dependency_overrides
    }
    yield
    app.dependency_overrides.update(saved)


def test_the_sweep_covers_enough_operations(no_overrides: None) -> None:
    protected = [op for op in _operations() if REGISTRY[op].kind != EXEMPT]

    assert len(protected) >= MIN_OPERATIONS


def test_every_non_exempt_operation_answers_401_without_a_key(no_overrides: None) -> None:
    client = TestClient(app)
    wrong: list[str] = []

    for method, path in _operations():
        if REGISTRY[(method, path)].kind == EXEMPT:
            continue
        status = client.request(method, _url(path), json={}).status_code
        if status != 401:
            wrong.append(f"{method} {path} -> {status}")

    assert wrong == [], f"operations that did not answer 401: {wrong}"
