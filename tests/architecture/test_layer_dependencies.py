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

# Each entry point may import exactly one module: the one that builds its
# application. The public entry point is ADR 0102, decision 6.
ENTRY_POINTS = {
    "app/main.py": "app.presentation.api",
    "app/public_main.py": "app.presentation.public.composition",
}

# Each composition root names the one infrastructure prefix it may import,
# a module of it or the prefix itself, and the third-party packages it may
# import on top of its layer. The public root takes only the public read
# package and no pool library: the package opens the pool (ADR 0104).
COMPOSITION_ROOTS: dict[str, tuple[str, frozenset[str]]] = {
    "app/presentation/dependencies.py": (
        "app.infrastructure",
        frozenset({"psycopg_pool"}),
    ),
    "app/presentation/public/composition.py": (
        "app.infrastructure.public_read",
        frozenset(),
    ),
}

# What each layer may import from this application. The layers depend
# inward: the domain knows nothing outside itself, and the application
# knows only the domain.
INTERNAL = {
    "domain": {"domain"},
    "application": {"application", "domain"},
    "infrastructure": {"infrastructure", "domain"},
    "presentation": {"presentation", "application", "domain"},
}

# The modules of the application layer that infrastructure imports: the
# ports that its adapters implement. Each one is named in full, and a
# module whose name only starts with one of them is still refused.
PORTS_IMPLEMENTED = {
    "app.application.scheduler_leadership",
    "app.application.public_read_port",
}

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
    if rel in ENTRY_POINTS:
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
        only = ENTRY_POINTS[rel]
        if module == only:
            return None
        return f"the entry point may import only {only}, not {module}"

    target = module.split(".")[1] if "." in module else ""

    if layer == "infrastructure" and target == "application":
        if module in PORTS_IMPLEMENTED:
            return None
        return f"infrastructure may import only {sorted(PORTS_IMPLEMENTED)}, not {module}"

    root = COMPOSITION_ROOTS.get(rel)
    if root is not None and target == "infrastructure":
        prefix = root[0]
        if module == prefix or module.startswith(prefix + "."):
            return None
        return f"this composition root may import only {prefix}, not {module}"

    allowed = set(INTERNAL[layer])

    if target in allowed:
        return None
    return f"{layer} may not import {module}"


def _third_party_ok(rel: str, layer: str, top: str) -> bool:
    if top == "__future__" or top in sys.stdlib_module_names:
        return True
    allowed = THIRD_PARTY.get(layer, frozenset())
    root = COMPOSITION_ROOTS.get(rel)
    if root is not None:
        allowed = allowed | root[1]
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
PUBLIC_PORT_MODULE = "app.application.public_read_port"
NEAR_MISS_MODULE = "app.application.public_read_port_extra"

# ADR 0102, decision 6: the public entry point and the public composition root.
PUBLIC_ENTRY = "app/public_main.py"
PUBLIC_ROOT = "app/presentation/public/composition.py"
PUBLIC_COMPOSITION_MODULE = "app.presentation.public.composition"
PUBLIC_READ_PACKAGE = "app.infrastructure.public_read"
PUBLIC_POOL_MODULE = "app.infrastructure.public_read.public_pool"
PUBLIC_READER_MODULE = "app.infrastructure.public_read.postgres_public_reader"
PUBLIC_READ_NEAR_MISS = "app.infrastructure.public_read_extra"
CREDENTIALS_MODULE = "app.infrastructure.database_credentials"


@pytest.mark.parametrize(
    ("rel", "layer", "module", "allowed"),
    [
        ("app/domain/x.py", "domain", DOMAIN_MODULE, True),
        ("app/domain/x.py", "domain", APPLICATION_MODULE, False),
        ("app/application/x.py", "application", DOMAIN_MODULE, True),
        ("app/application/x.py", "application", INFRASTRUCTURE_MODULE, False),
        ("app/infrastructure/x.py", "infrastructure", PORT_MODULE, True),
        ("app/infrastructure/x.py", "infrastructure", APPLICATION_MODULE, False),
        ("app/infrastructure/x.py", "infrastructure", PUBLIC_PORT_MODULE, True),
        ("app/infrastructure/x.py", "infrastructure", NEAR_MISS_MODULE, False),
        ("app/presentation/x.py", "presentation", INFRASTRUCTURE_MODULE, False),
        ("app/presentation/dependencies.py", "presentation", INFRASTRUCTURE_MODULE, True),
        ("app/main.py", "main", "app.presentation.api", True),
        ("app/main.py", "main", DOMAIN_MODULE, False),
        (PUBLIC_ENTRY, "main", PUBLIC_COMPOSITION_MODULE, True),
        (PUBLIC_ENTRY, "main", "app.presentation.api", False),
        (PUBLIC_ENTRY, "main", PUBLIC_READ_PACKAGE, False),
        (PUBLIC_ENTRY, "main", PUBLIC_POOL_MODULE, False),
        ("app/main.py", "main", PUBLIC_COMPOSITION_MODULE, False),
        (PUBLIC_ENTRY, "main", PUBLIC_COMPOSITION_MODULE + "_extra", False),
        (PUBLIC_ENTRY, "main", PUBLIC_COMPOSITION_MODULE + ".sub", False),
        ("app/main.py", "main", "app.presentation.api_extra", False),
        (PUBLIC_ROOT, "presentation", PUBLIC_READ_PACKAGE, True),
        (PUBLIC_ROOT, "presentation", PUBLIC_POOL_MODULE, True),
        (PUBLIC_ROOT, "presentation", PUBLIC_READER_MODULE, True),
        (PUBLIC_ROOT, "presentation", INFRASTRUCTURE_MODULE, False),
        (PUBLIC_ROOT, "presentation", "app.infrastructure", False),
        (PUBLIC_ROOT, "presentation", PUBLIC_READ_NEAR_MISS, False),
        (PUBLIC_ROOT, "presentation", CREDENTIALS_MODULE, False),
        ("app/presentation/public/app.py", "presentation", PUBLIC_POOL_MODULE, False),
        ("app/presentation/dependencies.py", "presentation", PUBLIC_POOL_MODULE, True),
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
        (PUBLIC_ROOT, "presentation", "psycopg_pool", False),
        (PUBLIC_ROOT, "presentation", "psycopg", False),
        (PUBLIC_ROOT, "presentation", "fastapi", True),
        (PUBLIC_ENTRY, "main", "fastapi", False),
    ],
)
def test_third_party_imports_follow_the_layer_rules(
    rel: str, layer: str, package: str, allowed: bool
) -> None:
    assert _third_party_ok(rel, layer, package) is allowed


@pytest.mark.parametrize(
    ("rel", "layer"),
    [
        ("app/main.py", "main"),
        (PUBLIC_ENTRY, "main"),
        (PUBLIC_ROOT, "presentation"),
        ("app/public_other.py", None),
        ("app/stray.py", None),
    ],
)
def test_the_layer_of_a_path(rel: str, layer: str | None) -> None:
    assert _layer(rel) == layer
