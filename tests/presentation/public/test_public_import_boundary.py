"""
ADR 0094, decisions 3, 4 and 7. The public package may import only what
the ADR lets it import. A static scan reads each import statement the way
Python resolves it, including relative imports and the names that
"from package import name" brings in, and flags any that reach the private
API, the private response schemas, a worker loop, or an application
service that is not on the allowlist.

The allowlist starts empty. A service is added here, by name, in the same
change that first imports it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.import_boundary import imported_names, violations

PACKAGE = "app.presentation.public"
PACKAGE_DIR = Path(__file__).resolve().parents[3] / "app" / "presentation" / "public"

FORBIDDEN_PREFIXES = (
    "app.presentation.routers",
    "app.presentation.dependencies",
    "app.presentation.api",
    "app.presentation.schemas",
    "app.application.workers",
)
ALLOWED_SERVICES: frozenset[str] = frozenset()


def _violations(source: str) -> list[str]:
    return violations(source, PACKAGE, FORBIDDEN_PREFIXES, ALLOWED_SERVICES)


@pytest.mark.parametrize(
    "source",
    [
        "from app.presentation.routers import nodes",
        "from app.presentation import dependencies",
        "from app.presentation import api",
        "from app.presentation import schemas",
        "from app.presentation.schemas.node_response import NodeResponse",
        "import app.presentation.dependencies",
        "import app.presentation.dependencies as private",
        "from ..routers import nodes",
        "from .. import dependencies",
        "from ...application.workers import loop",
    ],
)
def test_an_import_of_the_private_api_is_flagged(source: str) -> None:
    assert len(_violations(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "from app.application.services.job_supervisor import JobSupervisor",
        "from app.application.services.start_job_service import StartJobService",
        "from app.application.services.drain_node_service import DrainNodeService",
        "from app.application.services import report_job_outcome_service",
        "import app.application.services.mark_dead_workers_service",
    ],
)
def test_a_service_that_is_not_on_the_allowlist_is_flagged(source: str) -> None:
    assert len(_violations(source)) == 1


def test_a_service_on_the_allowlist_is_accepted_and_its_neighbours_are_not() -> None:
    allowed = frozenset({"list_nodes_service"})
    listed = "from app.application.services.list_nodes_service import Service"
    other = "from app.application.services.get_node_service import Service"

    assert violations(listed, PACKAGE, FORBIDDEN_PREFIXES, allowed) == []
    assert len(violations(other, PACKAGE, FORBIDDEN_PREFIXES, allowed)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "import os",
        "from fastapi import FastAPI",
        "from app.domain.value_objects.tenant_id import TenantId",
        "from app.presentation.public.settings import PublicSettings",
        "from . import settings",
        "from .settings import PublicSettings",
        "from app.presentation.apiary import honey",
    ],
)
def test_an_ordinary_import_is_not_flagged(source: str) -> None:
    assert _violations(source) == []


def test_a_violation_names_the_line_and_the_module() -> None:
    source = "import os\n\nfrom app.presentation import dependencies\n"

    (message,) = _violations(source)

    assert "line 3" in message
    assert "app.presentation.dependencies" in message


def test_the_public_package_stays_inside_the_boundary() -> None:
    problems: list[str] = []
    seen: set[str] = set()

    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        relative = path.relative_to(PACKAGE_DIR).parent.parts
        package = ".".join((PACKAGE, *relative))
        source = path.read_text(encoding="utf-8")

        seen.update(name for _, name in imported_names(source, package))
        problems += [
            f"{path.name}: {message}"
            for message in violations(
                source, package, FORBIDDEN_PREFIXES, ALLOWED_SERVICES
            )
        ]

    assert any(name.startswith("fastapi") for name in seen), (
        "the scan read no imports, so it proves nothing"
    )
    assert problems == [], "\n" + "\n".join(problems)


def test_a_relative_import_above_the_package_is_an_error_not_a_pass() -> None:
    with pytest.raises(ValueError, match="beyond the package"):
        _violations("from .... import secrets")
