"""ADR 0064, point 10: every route is classified, and none ships unclassified.

The OpenAPI schema is the list of routes. Each one is either scoped to
the caller's tenant and proven by a two-tenant test, exempt with a
written reason, or open with the ADR that will close it. A route in
none of these fails the build.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass
from pathlib import Path

from fastapi.routing import APIRoute

from app.presentation.api import app

TESTS = Path(__file__).resolve().parent
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

SCOPED = "scoped"
EXEMPT = "exempt"
OPEN = "open"

Route = tuple[str, str]


@dataclass(frozen=True)
class Entry:
    """
    kind is scoped, exempt or open. For a scoped route, detail is the
    file under tests/presentation that proves it. Otherwise it is the
    reason.
    """

    kind: str
    detail: str


def _scoped(proof: str) -> Entry:
    return Entry(SCOPED, proof)


_KEYS = "test_api_key_tenant_isolation_api.py"
_EVENTS = "test_event_routes_tenant_isolation_api.py"
_JOBS = "test_job_routes_tenant_isolation_api.py"
_NODES = "test_node_routes_tenant_isolation_api.py"
_NODE_CREATE = "test_create_node_tenant_api.py"
_W_REGISTER = "test_worker_routes_tenant_isolation_api.py"
_W_READ = "test_worker_read_routes_tenant_isolation_api.py"
_W_RENEW = "test_worker_renew_route_tenant_isolation_api.py"
_W_START = "test_worker_start_route_tenant_isolation_api.py"
_W_OUTCOME = "test_worker_outcome_routes_tenant_isolation_api.py"
_W_BEAT = "test_worker_heartbeat_route_tenant_isolation_api.py"
_PROBE = "Probe named exempt by ADR 0064 point 10. Returns a status, no tenant data."

REGISTRY: dict[Route, Entry] = {
    ("GET", "/"): Entry(
        EXEMPT, "Root route named exempt by ADR 0064 point 10. Returns fixed text."
    ),
    ("GET", "/health"): Entry(EXEMPT, _PROBE),
    ("GET", "/livez"): Entry(EXEMPT, _PROBE),
    ("POST", "/api-keys"): _scoped(_KEYS),
    ("GET", "/api-keys/{api_key_id}/issued"): _scoped(_KEYS),
    ("POST", "/api-keys/{api_key_id}/revoke"): _scoped(_KEYS),
    ("GET", "/cluster/capacity"): _scoped(_NODES),
    ("GET", "/cluster/health"): _scoped(_NODES),
    ("GET", "/cluster/utilization"): _scoped(_NODES),
    ("GET", "/events"): _scoped(_EVENTS),
    ("GET", "/jobs"): _scoped(_JOBS),
    ("POST", "/jobs"): _scoped(_JOBS),
    ("GET", "/jobs/queued"): _scoped(_JOBS),
    ("GET", "/jobs/{job_id}"): _scoped(_JOBS),
    ("GET", "/jobs/{job_id}/history"): _scoped(_JOBS),
    ("POST", "/jobs/{job_id}/cancel"): _scoped(_JOBS),
    ("POST", "/jobs/{job_id}/retry"): _scoped(_JOBS),
    ("GET", "/nodes"): _scoped(_NODES),
    ("POST", "/nodes"): _scoped(_NODE_CREATE),
    ("GET", "/nodes/offline"): _scoped(_NODES),
    ("GET", "/nodes/{node_id}"): _scoped(_NODES),
    ("DELETE", "/nodes/{node_id}"): _scoped(_NODES),
    ("POST", "/nodes/{node_id}/drain"): _scoped(_NODES),
    ("POST", "/nodes/{node_id}/heartbeat"): _scoped(_NODES),
    ("GET", "/workers"): _scoped(_W_READ),
    ("POST", "/workers"): _scoped(_W_REGISTER),
    ("GET", "/workers/{worker_id}"): _scoped(_W_READ),
    ("POST", "/workers/{worker_id}/heartbeat"): _scoped(_W_BEAT),
    ("POST", "/workers/{worker_id}/lease/renew"): _scoped(_W_RENEW),
    ("POST", "/workers/{worker_id}/jobs/{job_id}/start"): _scoped(_W_START),
    ("POST", "/workers/{worker_id}/jobs/{job_id}/complete"): _scoped(_W_OUTCOME),
    ("POST", "/workers/{worker_id}/jobs/{job_id}/fail"): _scoped(_W_OUTCOME),
    ("POST", "/workers/{worker_id}/jobs/{job_id}/cancel"): _scoped(_W_OUTCOME),
}


def _listing(routes: set[Route]) -> str:
    return ", ".join(f"{m} {p}" for m, p in sorted(routes)) or "none"


def _schema_operations() -> set[Route]:
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method in HTTP_METHODS
    }


def _router_routes() -> dict[Route, APIRoute]:
    package = importlib.import_module("app.presentation.routers")
    found: dict[Route, APIRoute] = {}
    for info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{info.name}")
        router = getattr(module, "router", None)
        if router is None:
            continue
        for route in router.routes:
            if isinstance(route, APIRoute):
                for method in route.methods - {"HEAD", "OPTIONS"}:
                    found[(method, route.path)] = route
    return found


def _word(path: str) -> str:
    literals = [s for s in path.strip("/").split("/") if not s.startswith("{")]
    return literals[-1] if literals else ""


def _mentions_path(source: str, path: str) -> bool:
    """
    A proof names a route by its path ("/drain"), or, when it loops over
    several routes, by the action as a quoted value ("complete").
    """
    word = _word(path)
    return f"/{word}" in source or f'"{word}"' in source


def _mentions_method(source: str, method: str) -> bool:
    """A proof calls the method directly or lists it as a quoted value."""
    return f".{method.lower()}(" in source or f'"{method}"' in source


def test_every_route_is_classified_and_nothing_is_stale() -> None:
    operations = _schema_operations()
    registered = set(REGISTRY)

    assert operations == registered, (
        f"routes with no classification: {_listing(operations - registered)}; "
        f"registry entries for routes that do not exist: "
        f"{_listing(registered - operations)}"
    )


def test_no_router_route_is_hidden_from_the_schema() -> None:
    hidden = set(_router_routes()) - _schema_operations()

    assert not hidden, f"routes missing from the schema: {_listing(hidden)}"


def test_a_scoped_route_takes_the_caller_and_has_a_proof_that_names_it() -> None:
    routes = _router_routes()
    problems: list[str] = []

    for (method, path), entry in sorted(REGISTRY.items()):
        if entry.kind != SCOPED:
            continue
        label = f"{method} {path}"
        route = routes.get((method, path))
        if route is None:
            problems.append(f"{label}: no handler in a router module")
        elif "caller" not in inspect.signature(route.endpoint).parameters:
            problems.append(f"{label}: the handler does not take the caller")

        proof = TESTS / entry.detail
        if not proof.is_file():
            problems.append(f"{label}: proof file {entry.detail} does not exist")
            continue
        source = proof.read_text()
        if not _mentions_path(source, path):
            problems.append(f"{label}: {entry.detail} never names /{_word(path)}")
        elif not _mentions_method(source, method):
            problems.append(f"{label}: {entry.detail} never uses {method}")

    assert not problems, "; ".join(problems)


def test_an_exempt_or_open_route_gives_its_reason() -> None:
    problems: list[str] = []

    for (method, path), entry in sorted(REGISTRY.items()):
        label = f"{method} {path}"
        if entry.kind not in {SCOPED, EXEMPT, OPEN}:
            problems.append(f"{label}: unknown kind {entry.kind!r}")
        elif entry.kind != SCOPED and len(entry.detail.split()) < 4:
            problems.append(f"{label}: give a reason")
        elif entry.kind == OPEN and "ADR" not in entry.detail:
            problems.append(f"{label}: an open route names the ADR that closes it")

    assert not problems, "; ".join(problems)
