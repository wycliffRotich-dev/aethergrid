"""
The layer rules of ADR 0082, checked on the source of app/.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"

ENTRY_POINT = "app/main.py"
COMPOSITION_ROOT = "app/presentation/dependencies.py"

# What each layer may import from this application. The layers depend
# inward: the domain knows nothing outside itself, and the application
# knows only the domain.
INTERNAL = {
    "domain": {"domain"},
    "application": {"application", "domain"},
    "infrastructure": {"infrastructure", "domain"},
    "presentation": {"presentation", "application", "domain"},
}

# The one module of the application layer that infrastructure imports:
# the port that its leadership adapters implement.
PORTS_IMPLEMENTED = {"app.application.scheduler_leadership"}

# Third-party packages each layer may import. The domain and the
# application take the standard library and nothing else.
THIRD_PARTY = {
    "domain": frozenset(),
    "application": frozenset(),
    "infrastructure": frozenset({"psycopg", "psycopg_pool"}),
    "presentation": frozenset({"fastapi", "pydantic", "starlette"}),
}


@dataclass(frozen=True)
class Import:
    path: str
    line: int
    module: str
    level: int


def _python_files() -> list[Path]:
    return sorted(APP.rglob("*.py"))


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _layer(rel: str) -> str | None:
    if rel == ENTRY_POINT:
        return "main"
    parts = rel.split("/")
    if len(parts) > 2 and parts[1] in INTERNAL:
        return parts[1]
    return None


def _imports(path: Path) -> Iterator[Import]:
    rel = _relative(path)
    package = rel.split("/")[:-1]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield Import(rel, node.lineno, alias.name, 0)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - (node.level - 1)] if node.level else []
            named = node.module.split(".") if node.module else []
            parts = [*base, *named]
            if node.module is None or parts == ["app"]:
                # "from . import x" and "from app import x": x may be a module.
                for alias in node.names:
                    yield Import(rel, node.lineno, ".".join([*parts, alias.name]), node.level)
            else:
                yield Import(rel, node.lineno, ".".join(parts), node.level)


def _dynamic_imports(path: Path) -> Iterator[int]:
    """
    Yield the line of every __import__ or import_module call. A module
    named by a string is a dependency that the import checks cannot see.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=_relative(path))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        else:
            continue

        if name in {"__import__", "import_module"}:
            yield node.lineno


def _internal_problem(rel: str, layer: str, module: str) -> str | None:
    if layer == "main":
        if module == "app.presentation.api":
            return None
        return f"the entry point may import only app.presentation.api, not {module}"

    target = module.split(".")[1] if "." in module else ""

    if layer == "infrastructure" and target == "application":
        if module in PORTS_IMPLEMENTED:
            return None
        return f"infrastructure may import only {sorted(PORTS_IMPLEMENTED)}, not {module}"

    allowed = set(INTERNAL[layer])
    if rel == COMPOSITION_ROOT:
        allowed.add("infrastructure")

    if target in allowed:
        return None
    return f"{layer} may not import {module}"


def _third_party_ok(rel: str, layer: str, top: str) -> bool:
    if top == "__future__" or top in sys.stdlib_module_names:
        return True
    allowed = THIRD_PARTY.get(layer, frozenset())
    if rel == COMPOSITION_ROOT:
        allowed = allowed | {"psycopg_pool"}
    return top in allowed


def _violations(path: Path) -> list[str]:
    rel = _relative(path)
    layer = _layer(rel)
    found: list[str] = []

    if layer is None:
        found.append(f"VIOLATION {rel}: not in a layer and not the entry point")
        return found

    for imp in _imports(path):
        where = f"VIOLATION {rel}:{imp.line}:"
        top = imp.module.split(".")[0]

        if imp.level > 1:
            found.append(f"{where} a relative import climbs out of its package")

        if top == "app":
            problem = _internal_problem(rel, layer, imp.module)
            if problem is not None:
                found.append(f"{where} {problem}")
        elif not _third_party_ok(rel, layer, top):
            found.append(f"{where} {layer} may not import {top}")

    for line in _dynamic_imports(path):
        found.append(f"VIOLATION {rel}:{line}: a dynamic import hides a dependency")

    return found


def test_every_module_belongs_to_a_layer_or_is_the_entry_point() -> None:
    strays = [_relative(p) for p in _python_files() if _layer(_relative(p)) is None]

    assert strays == []


def test_the_layers_depend_only_inward() -> None:
    found = [line for path in _python_files() for line in _violations(path)]

    assert found == [], "\n" + "\n".join(found)


DOMAIN_MODULE = "app.domain.entities.job"
APPLICATION_MODULE = "app.application.services.get_job_service"
INFRASTRUCTURE_MODULE = "app.infrastructure.repositories.postgres_job_repository"
PORT_MODULE = "app.application.scheduler_leadership"


@pytest.mark.parametrize(
    ("rel", "layer", "module", "allowed"),
    [
        ("app/domain/x.py", "domain", DOMAIN_MODULE, True),
        ("app/domain/x.py", "domain", APPLICATION_MODULE, False),
        ("app/application/x.py", "application", DOMAIN_MODULE, True),
        ("app/application/x.py", "application", INFRASTRUCTURE_MODULE, False),
        ("app/infrastructure/x.py", "infrastructure", PORT_MODULE, True),
        ("app/infrastructure/x.py", "infrastructure", APPLICATION_MODULE, False),
        ("app/presentation/x.py", "presentation", INFRASTRUCTURE_MODULE, False),
        ("app/presentation/dependencies.py", "presentation", INFRASTRUCTURE_MODULE, True),
        ("app/main.py", "main", "app.presentation.api", True),
        ("app/main.py", "main", DOMAIN_MODULE, False),
    ],
)
def test_internal_imports_follow_the_layer_rules(
    rel: str, layer: str, module: str, allowed: bool
) -> None:
    assert (_internal_problem(rel, layer, module) is None) is allowed


@pytest.mark.parametrize(
    ("rel", "layer", "package", "allowed"),
    [
        ("app/domain/x.py", "domain", "json", True),
        ("app/domain/x.py", "domain", "psycopg", False),
        ("app/application/x.py", "application", "fastapi", False),
        ("app/infrastructure/x.py", "infrastructure", "psycopg", True),
        ("app/infrastructure/x.py", "infrastructure", "fastapi", False),
        ("app/presentation/x.py", "presentation", "fastapi", True),
        ("app/presentation/x.py", "presentation", "psycopg_pool", False),
        ("app/presentation/dependencies.py", "presentation", "psycopg_pool", True),
    ],
)
def test_third_party_imports_follow_the_layer_rules(
    rel: str, layer: str, package: str, allowed: bool
) -> None:
    assert _third_party_ok(rel, layer, package) is allowed
