"""
A readiness or liveness probe that carries no credential must hit a
route the registry marks exempt (ADR 0064 point 10). The e2e job once
polled /docs, which answered 404 after ADR 0077, and failed on main.

The exempt paths come from the route registry, so there is one source
of truth. A URL on the line of an Authorization header is authenticated
by construction and is skipped.

Limit: a probe built from a variable, or split across lines, is not
seen. This guards against the /docs mistake, not every possible one.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.presentation.test_route_tenancy_registry import EXEMPT, REGISTRY

ROOT = Path(__file__).resolve().parents[2]
URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):8000(?P<path>/[A-Za-z0-9_\-./]*)?")
MIN_PROBES = 3


def _exempt_paths() -> set[str]:
    return {path for (_, path), entry in REGISTRY.items() if entry.kind == EXEMPT}


def _files() -> list[Path]:
    return sorted((ROOT / ".github" / "workflows").glob("*.yml")) + [ROOT / "docker-compose.yml"]


def _probes() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for file in _files():
        for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
            if "Authorization" in line:
                continue
            for match in URL.finditer(line):
                name = file.relative_to(ROOT).as_posix()
                found.append((name, number, match.group("path") or "/"))
    return found


def test_the_scan_finds_the_probes() -> None:
    assert len(_probes()) >= MIN_PROBES


def test_every_unauthenticated_probe_hits_an_exempt_route() -> None:
    exempt = _exempt_paths()
    offenders = [f"{f}:{n} {p}" for f, n, p in _probes() if p not in exempt]

    assert offenders == [], f"probes outside the exempt set {sorted(exempt)}: {offenders}"
