"""
Static import scan used by the ADR 0094 boundary tests.

It resolves every import statement to the dotted names Python would load,
including relative imports and the names that "from package import name"
brings in, then checks them against a list of forbidden prefixes and an
allowlist of application services.

It reads source text only. An import made at run time through importlib
or __import__ is not seen here.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable

SERVICES = "app.application.services"


def _resolve(module: str | None, level: int, package: str) -> str:
    if level == 0:
        return module or ""

    parts = package.split(".")
    keep = len(parts) - (level - 1)

    if keep < 1:
        raise ValueError(f"a relative import goes beyond the package {package}")

    base = ".".join(parts[:keep])

    return f"{base}.{module}" if module else base


def imported_names(source: str, package: str) -> list[tuple[int, str]]:
    """
    Return (line, dotted name) for every name the source imports.

    package is the package that contains the file, so that a relative
    import resolves the way Python resolves it.
    """
    found: list[tuple[int, str]] = []

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = _resolve(node.module, node.level, package)

            for alias in node.names:
                name = base if alias.name == "*" else f"{base}.{alias.name}"
                found.append((node.lineno, name))

    return sorted(found)


def _under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def violations(
    source: str,
    package: str,
    forbidden_prefixes: Iterable[str],
    allowed_services: frozenset[str],
) -> list[str]:
    """Return one message for each import that crosses the boundary."""
    prefixes = tuple(forbidden_prefixes)
    problems: list[str] = []

    for line, name in imported_names(source, package):
        if any(_under(name, prefix) for prefix in prefixes):
            problems.append(f"line {line} imports {name}, which is private to the API")
        elif _under(name, SERVICES):
            parts = name.split(".")
            service = parts[3] if len(parts) > 3 else None

            if service is None or service not in allowed_services:
                problems.append(
                    f"line {line} imports {name}, "
                    "a service that is not on the allowlist"
                )

    return problems
