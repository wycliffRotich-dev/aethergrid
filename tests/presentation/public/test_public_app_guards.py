"""
ADR 0094. The public app is a separate, read-only application. These
checks are the inverse of the ADR 0064 route tests: every route is a GET,
the paths are an explicit allowlist, and nothing that writes or schedules
is reachable from the package.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.presentation.public.app import create_public_app
from app.presentation.public.settings import PublicSettings

PACKAGE = Path(__file__).resolve().parents[3] / "app" / "presentation" / "public"

TENANT = "11111111-1111-1111-1111-111111111111"
ORIGIN = "https://demo.example.org"

# Every path the public app serves. A route is added here on purpose, in
# the same change that adds the route.
ALLOWED_PATHS = {"/healthz"}

FORBIDDEN_IMPORT_PREFIXES = (
    "app.presentation.routers",
    "app.presentation.dependencies",
    "app.presentation.api",
    "app.application.workers",
)
FORBIDDEN_SERVICE_WORDS = (
    "create_",
    "drain_",
    "remove_",
    "heartbeat_",
    "cancel_",
    "retry_",
    "revoke_",
    "renew_",
    "acquire_",
    "release_",
    "assign_",
    "cluster_tick",
    "scheduler",
    "reconciliation",
)


def _settings() -> PublicSettings:
    return PublicSettings.from_environment(
        {
            "AETHERGRID_PUBLIC_TENANT_ID": TENANT,
            "AETHERGRID_PUBLIC_ALLOWED_ORIGIN": ORIGIN,
        }
    )


def _app():
    return create_public_app(_settings())


def _imported_modules() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []

    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found += [(path.name, node.lineno, a.name) for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append((path.name, node.lineno, node.module))

    return found


def test_every_route_is_a_get() -> None:
    methods = {
        method
        for route in _app().routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }

    assert methods == {"GET"}


def test_the_paths_equal_the_allowlist() -> None:
    paths = {route.path for route in _app().routes if isinstance(route, APIRoute)}

    assert paths == ALLOWED_PATHS


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_write_method_is_refused_before_any_code_runs(method: str) -> None:
    client = TestClient(_app())

    assert client.request(method, "/healthz").status_code == 405


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/nodes"])
def test_nothing_outside_the_allowlist_is_served(path: str) -> None:
    client = TestClient(_app())

    assert client.get(path).status_code == 404


def test_the_app_starts_nothing() -> None:
    app = _app()

    assert app.router.on_startup == []
    assert app.router.on_shutdown == []


def test_the_package_imports_nothing_that_writes_or_schedules() -> None:
    bad: list[str] = []

    for name, line, module in _imported_modules():
        if module.startswith(FORBIDDEN_IMPORT_PREFIXES):
            bad.append(f"{name}:{line} imports {module}")

        if module.startswith("app.application.services."):
            leaf = module.rsplit(".", 1)[-1]
            if any(word in leaf for word in FORBIDDEN_SERVICE_WORDS):
                bad.append(f"{name}:{line} imports the service {leaf}")

    assert bad == [], "\n" + "\n".join(bad)


def test_the_check_would_flag_a_forbidden_import() -> None:
    source = "from app.application.services.drain_node_service import X\n"
    module = ast.parse(source).body[0]
    assert isinstance(module, ast.ImportFrom) and module.module is not None

    leaf = module.module.rsplit(".", 1)[-1]

    assert any(word in leaf for word in FORBIDDEN_SERVICE_WORDS)


def test_a_missing_tenant_stops_construction() -> None:
    with pytest.raises(ValueError, match="AETHERGRID_PUBLIC_TENANT_ID"):
        PublicSettings.from_environment(
            {"AETHERGRID_PUBLIC_ALLOWED_ORIGIN": ORIGIN}
        )


def test_a_malformed_tenant_stops_construction() -> None:
    with pytest.raises(ValueError, match="AETHERGRID_PUBLIC_TENANT_ID"):
        PublicSettings.from_environment(
            {
                "AETHERGRID_PUBLIC_TENANT_ID": "not-a-uuid",
                "AETHERGRID_PUBLIC_ALLOWED_ORIGIN": ORIGIN,
            }
        )


@pytest.mark.parametrize("origin", ["", "*", "http://", "demo.example.org", "https://a.org/path"])
def test_a_wrong_origin_stops_construction(origin: str) -> None:
    with pytest.raises(ValueError, match="AETHERGRID_PUBLIC_ALLOWED_ORIGIN"):
        PublicSettings.from_environment(
            {
                "AETHERGRID_PUBLIC_TENANT_ID": TENANT,
                "AETHERGRID_PUBLIC_ALLOWED_ORIGIN": origin,
            }
        )


def test_the_health_route_returns_a_fixed_body() -> None:
    response = TestClient(_app()).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
