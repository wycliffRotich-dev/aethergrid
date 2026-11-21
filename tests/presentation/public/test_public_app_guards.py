"""
ADR 0094. The public app is a separate, read-only application. These
checks are the inverse of the ADR 0064 route tests: every route is a GET,
the paths are an explicit allowlist, and nothing that writes or schedules
is reachable from the package.
"""

from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.presentation.public.app import create_public_app
from app.presentation.public.settings import PublicSettings
from tests.support.import_boundary import FORBIDDEN_PREFIXES, imported_names

PACKAGE = Path(__file__).resolve().parents[3] / "app" / "presentation" / "public"

ORIGIN = "https://demo.example.org"

# Every path the public app serves. A route is added here on purpose, in
# the same change that adds the route.
ALLOWED_PATHS = {"/healthz"}

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
            "AETHERGRID_PUBLIC_ALLOWED_ORIGIN": ORIGIN,
            "AETHERGRID_PUBLIC_DATABASE_URL": "postgresql://aethergrid_public@db.internal:5432/aethergrid",
            "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE": "/run/secrets/public_db_password",
            "AETHERGRID_PUBLIC_TRUSTED_PROXY_HOPS": "1",
        }
    )


def _app():
    return create_public_app(_settings())


def _imported_modules() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    root = PACKAGE.parents[2]

    for path in sorted(PACKAGE.rglob("*.py")):
        package = ".".join(path.parent.relative_to(root).parts)
        source = path.read_text(encoding="utf-8")
        found += [
            (path.name, line, name) for line, name in imported_names(source, package)
        ]

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


def test_a_lifespan_runs_on_entry_and_exit_and_adds_no_handler() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        events.append("enter")
        yield
        events.append("exit")

    app = create_public_app(_settings(), lifespan=lifespan)

    assert events == []

    with TestClient(app) as client:
        assert events == ["enter"]
        assert client.get("/healthz").status_code == 200

    assert events == ["enter", "exit"]
    assert app.router.on_startup == []
    assert app.router.on_shutdown == []


def _forbidden_imports(modules: list[tuple[str, int, str]]) -> list[str]:
    bad: list[str] = []

    for name, line, module in modules:
        if any(module == p or module.startswith(p + ".") for p in FORBIDDEN_PREFIXES):
            bad.append(f"{name}:{line} imports {module}")

        if module.startswith("app.application.services."):
            leaf = module.rsplit(".", 1)[-1]
            if any(word in leaf for word in FORBIDDEN_SERVICE_WORDS):
                bad.append(f"{name}:{line} imports the service {leaf}")

    return bad


def test_the_package_imports_nothing_that_writes_or_schedules() -> None:
    bad = _forbidden_imports(_imported_modules())

    assert bad == [], "\n" + "\n".join(bad)


def test_the_check_flags_a_listed_prefix_and_keeps_the_dot_boundary() -> None:
    modules = [
        ("x.py", 1, "app.infrastructure.repositories.node_repository"),
        ("x.py", 2, "app.presentation.apiary"),
    ]

    assert _forbidden_imports(modules) == [
        "x.py:1 imports app.infrastructure.repositories.node_repository"
    ]


def test_the_check_would_flag_a_forbidden_import() -> None:
    source = "from app.application.services.drain_node_service import X\n"
    module = ast.parse(source).body[0]
    assert isinstance(module, ast.ImportFrom) and module.module is not None

    leaf = module.module.rsplit(".", 1)[-1]

    assert any(word in leaf for word in FORBIDDEN_SERVICE_WORDS)


@pytest.mark.parametrize("origin", ["", "*", "http://", "demo.example.org", "https://a.org/path"])
def test_a_wrong_origin_stops_construction(origin: str) -> None:
    with pytest.raises(ValueError, match="AETHERGRID_PUBLIC_ALLOWED_ORIGIN"):
        PublicSettings.from_environment(
            {
                "AETHERGRID_PUBLIC_ALLOWED_ORIGIN": origin,
                "AETHERGRID_PUBLIC_DATABASE_URL": "postgresql://aethergrid_public@db.internal:5432/aethergrid",
                "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE": "/run/secrets/public_db_password",
                "AETHERGRID_PUBLIC_TRUSTED_PROXY_HOPS": "1",
            }
        )


def test_the_health_route_returns_a_fixed_body() -> None:
    response = TestClient(_app()).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
