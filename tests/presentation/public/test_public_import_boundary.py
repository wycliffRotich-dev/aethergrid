"""
ADR 0094, decisions 3, 4 and 7. The public package may import only what
the ADR lets it import. A static scan reads each import statement the way
Python resolves it, including relative imports and the names that
"from package import name" brings in, and flags any that reach the private
API, the private response schemas, a worker loop, or an application
service that is not on the allowlist.

The allowlist of services starts empty. A service is added here, by name,
in the same change that first imports it.

Other application modules are matched by exact module name against a
separate allowlist: the rate limiter (ADR 0103) and the read port
(ADR 0102, decision 5). The private repositories and the credential reader
are forbidden by prefix.
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
    "app.infrastructure.repositories",
    "app.infrastructure.database_credentials",
)
ALLOWED_SERVICES: frozenset[str] = frozenset()
ALLOWED_APPLICATION_MODULES: frozenset[str] = frozenset(
    {"public_rate_limiter", "public_read_port"}
)


def _violations(source: str) -> list[str]:
    return violations(
        source,
        PACKAGE,
        FORBIDDEN_PREFIXES,
        ALLOWED_SERVICES,
        allowed_application_modules=ALLOWED_APPLICATION_MODULES,
    )


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


def _check_modules(source: str, allowed: frozenset[str]) -> list[str]:
    return violations(
        source,
        PACKAGE,
        FORBIDDEN_PREFIXES,
        ALLOWED_SERVICES,
        allowed_application_modules=allowed,
    )


@pytest.mark.parametrize(
    "source",
    [
        "from app.application.scheduler_leadership import SchedulerLeadership",
        "from app.application import scheduler_leadership",
        "import app.application.scheduler_leadership",
        "from ...application import scheduler_leadership",
        "from app.application.public_read_port_extra import PublicNodeRecord",
        "from app.application import public_read_port_extra",
        "from app import application",
        "import app.application",
    ],
)
def test_an_application_module_that_is_not_on_the_allowlist_is_flagged(
    source: str,
) -> None:
    assert len(_violations(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "from app.infrastructure.repositories import job_repository",
        "from app.infrastructure.repositories.postgres_job_repository import Repo",
        "import app.infrastructure.repositories",
        "from app.infrastructure import repositories",
        "from app.infrastructure.database_credentials import read_password_file",
        "from app.infrastructure import database_credentials",
        "import app.infrastructure.database_credentials",
    ],
)
def test_a_private_repository_or_the_credential_reader_is_flagged(
    source: str,
) -> None:
    assert len(_violations(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "from app.application.public_rate_limiter import AnonymousRateLimiter",
        "from app.application.public_read_port import PublicNodeRecord",
        "from app.application import public_read_port",
        "import app.application.public_read_port",
        "from ...application import public_rate_limiter",
    ],
)
def test_an_application_module_on_the_allowlist_is_accepted(source: str) -> None:
    assert _violations(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "from app.infrastructure.repositoriesx import thing",
        "from app.infrastructure.database_credentials_extra import thing",
        "from app.applications import thing",
    ],
)
def test_a_name_that_only_starts_like_a_boundary_is_not_flagged(
    source: str,
) -> None:
    assert _violations(source) == []


def test_a_module_allowlist_is_matched_by_exact_name() -> None:
    allowed = frozenset({"public_read_port"})
    listed = "from app.application.public_read_port import PublicNodeRecord"
    longer = "from app.application.public_read_port_extra import PublicNodeRecord"
    shorter = "from app.application.public_read import PublicNodeRecord"

    assert _check_modules(listed, allowed) == []
    assert len(_check_modules(longer, allowed)) == 1
    assert len(_check_modules(shorter, allowed)) == 1


def test_an_empty_module_allowlist_refuses_every_application_module() -> None:
    source = "from app.application.public_read_port import PublicNodeRecord"

    assert len(_check_modules(source, frozenset())) == 1


def test_without_a_module_allowlist_only_the_older_rules_apply() -> None:
    source = "from app.application.scheduler_leadership import SchedulerLeadership"

    assert violations(source, PACKAGE, FORBIDDEN_PREFIXES, ALLOWED_SERVICES) == []


def test_a_module_violation_names_the_line_and_the_module() -> None:
    source = "import os\n\nfrom app.application import scheduler_leadership\n"

    (message,) = _violations(source)

    assert "line 3" in message
    assert "app.application.scheduler_leadership" in message
    assert "allowlist" in message


def test_a_violation_names_the_line_and_the_module() -> None:
    source = "import os\n\nfrom app.presentation import dependencies\n"

    (message,) = _violations(source)

    assert "line 3" in message
    assert "app.presentation.dependencies" in message


def _scan(directory: Path) -> tuple[list[str], set[str]]:
    """Scan every .py file under directory the way the real package is scanned."""
    problems: list[str] = []
    seen: set[str] = set()

    for path in sorted(directory.rglob("*.py")):
        relative = path.relative_to(directory).parent.parts
        package = ".".join((PACKAGE, *relative))
        source = path.read_text(encoding="utf-8")

        seen.update(name for _, name in imported_names(source, package))
        problems += [
            f"{path.name}: {message}"
            for message in violations(
                source,
                package,
                FORBIDDEN_PREFIXES,
                ALLOWED_SERVICES,
                allowed_application_modules=ALLOWED_APPLICATION_MODULES,
            )
        ]

    return problems, seen


def test_the_scan_flags_bad_imports_in_a_top_level_and_a_nested_file(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "inner"
    nested.mkdir()
    (tmp_path / "top.py").write_text(
        "from app.application.scheduler_leadership import SchedulerLeadership\n",
        encoding="utf-8",
    )
    (nested / "deep.py").write_text(
        "from app.infrastructure.repositories import job_repository\n"
        "from ... import dependencies\n"
        "from app.application.public_read_port import PublicNodeRecord\n",
        encoding="utf-8",
    )

    problems, seen = _scan(tmp_path)

    assert len(problems) == 3, problems
    assert any(
        p.startswith("top.py:") and "scheduler_leadership" in p for p in problems
    )
    assert any(
        p.startswith("deep.py:") and "infrastructure.repositories" in p
        for p in problems
    )
    assert any(
        p.startswith("deep.py:") and "app.presentation.dependencies" in p
        for p in problems
    )
    assert "app.application.public_read_port.PublicNodeRecord" in seen


def test_the_public_package_stays_inside_the_boundary() -> None:
    problems, seen = _scan(PACKAGE_DIR)

    assert any(name.startswith("fastapi") for name in seen), (
        "the scan read no imports, so it proves nothing"
    )
    limiter = "app.application.public_rate_limiter"
    assert any(name.startswith(limiter) for name in seen), (
        "the scan saw no application import, so the module rule is untested here"
    )
    assert problems == [], "\n" + "\n".join(problems)


def test_a_relative_import_above_the_package_is_an_error_not_a_pass() -> None:
    with pytest.raises(ValueError, match="beyond the package"):
        _violations("from .... import secrets")
