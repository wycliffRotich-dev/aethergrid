from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Route

from app.presentation.api import _docs_enabled, app

DOC_PATHS = ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"]


@pytest.mark.parametrize("path", DOC_PATHS)
def test_doc_routes_are_not_served_without_a_key(path: str) -> None:
    assert TestClient(app).get(path).status_code == 404


def test_no_framework_added_route_escapes_the_registry() -> None:
    offenders = [route.path for route in app.routes if type(route) is Route]

    assert offenders == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, False), ("", False), ("0", False), ("1", True), ("true", True), ("YES", True)],
)
def test_docs_flag_is_an_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: bool
) -> None:
    if value is None:
        monkeypatch.delenv("NEUROMESH_ENABLE_API_DOCS", raising=False)
    else:
        monkeypatch.setenv("NEUROMESH_ENABLE_API_DOCS", value)

    assert _docs_enabled() is expected
