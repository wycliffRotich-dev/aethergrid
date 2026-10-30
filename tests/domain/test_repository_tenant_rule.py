from __future__ import annotations

import importlib
import inspect
import typing
from abc import ABC, abstractmethod
from pathlib import Path

import pytest

from app.domain.entities.api_key import ApiKey
from app.domain.entities.event import Event
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.repositories.api_key_repository import (
    ApiKeyRepository,
)
from app.domain.repositories.event_repository import EventRepository
from app.domain.repositories.job_repository import JobRepository
from app.domain.repositories.lease_repository import LeaseRepository
from app.domain.repositories.node_repository import NodeRepository
from app.domain.repositories.tenant_repository import TenantRepository
from app.domain.repositories.worker_repository import WorkerRepository
from app.domain.value_objects.tenant_id import TenantId

# Repositories already held to ADR 0064, point 4. A repository
# joins this list in the same change that scopes it.
SCOPED_REPOSITORIES = [
    ApiKeyRepository,
    EventRepository,
    JobRepository,
    LeaseRepository,
    NodeRepository,
    WorkerRepository,
]

# Repositories exempt from the rule, each with its reason. A tenant is
# the isolation boundary and not a record owned by one, so its
# repository takes no tenant argument (ADR 0064, point 4).
EXEMPT_REPOSITORIES: dict[type, str] = {
    TenantRepository: "a tenant is the boundary itself, not a record owned by one",
}

# The abstract methods of the exempt tenant repository. A new one fails
# the test below until it is classified here, on purpose.
TENANT_REPOSITORY_METHODS = {"save", "get_by_id", "get_by_name"}

REPOSITORIES_DIR = Path(__file__).resolve().parents[2] / "app" / "domain" / "repositories"

# Entity types that carry their own tenant_id, so a method
# that takes one is scoped by that entity.
TENANT_CARRYING_ENTITIES = (ApiKey, Event, Job, Lease, Node, Worker)

ACROSS_TENANTS_SUFFIX = "_across_tenants"


def _abstract_methods(repository: type) -> list[str]:
    return [
        name
        for name, member in inspect.getmembers(repository)
        if getattr(member, "__isabstractmethod__", False)
    ]


def tenant_rule_violations(repository: type) -> list[str]:
    violations = []

    for name in _abstract_methods(repository):
        hints = typing.get_type_hints(getattr(repository, name))
        hints.pop("return", None)

        takes_tenant = any(hint is TenantId for hint in hints.values())
        takes_carrier = any(
            hint in TENANT_CARRYING_ENTITIES for hint in hints.values()
        )

        if name.endswith(ACROSS_TENANTS_SUFFIX):
            if takes_tenant:
                violations.append(
                    f"{name} is named across tenants but takes a TenantId"
                )
            continue

        if not (takes_tenant or takes_carrier):
            violations.append(
                f"{name} takes no TenantId and is not named "
                f"*{ACROSS_TENANTS_SUFFIX}"
            )

    return violations


@pytest.mark.parametrize("repository", SCOPED_REPOSITORIES)
def test_scoped_repositories_follow_the_tenant_rule(repository):
    assert _abstract_methods(repository), "no abstract methods found"
    assert tenant_rule_violations(repository) == []


def test_the_check_flags_an_unscoped_method():
    class UnscopedRepository(ABC):
        @abstractmethod
        def list_all(self) -> list[ApiKey]:
            raise NotImplementedError

    assert tenant_rule_violations(UnscopedRepository) == [
        "list_all takes no TenantId and is not named *_across_tenants"
    ]


def test_the_check_flags_a_mislabeled_method():
    class MislabeledRepository(ABC):
        @abstractmethod
        def get_by_hash_across_tenants(
            self,
            key_hash: str,
            tenant_id: TenantId,
        ) -> ApiKey | None:
            raise NotImplementedError

    assert tenant_rule_violations(MislabeledRepository) == [
        "get_by_hash_across_tenants is named across tenants "
        "but takes a TenantId"
    ]


def _repository_ports() -> set[type]:
    """Every abstract repository class declared under app/domain/repositories."""
    ports: set[type] = set()

    for path in sorted(REPOSITORIES_DIR.glob("*_repository.py")):
        module = importlib.import_module(f"app.domain.repositories.{path.stem}")

        for _, member in inspect.getmembers(module, inspect.isclass):
            if member.__module__ == module.__name__ and inspect.isabstract(member):
                ports.add(member)

    return ports


def test_every_repository_port_is_scoped_or_exempt():
    classified = set(SCOPED_REPOSITORIES) | set(EXEMPT_REPOSITORIES)

    unclassified = sorted(port.__name__ for port in _repository_ports() - classified)

    assert unclassified == [], (
        f"{unclassified} is neither scoped nor exempt, so the tenant rule "
        "of ADR 0064 point 4 does not cover it"
    )


def test_no_classification_names_a_repository_that_is_gone():
    classified = set(SCOPED_REPOSITORIES) | set(EXEMPT_REPOSITORIES)

    stale = sorted(port.__name__ for port in classified - _repository_ports())

    assert stale == []


def test_the_exempt_tenant_repository_has_only_the_methods_it_was_written_for():
    assert set(_abstract_methods(TenantRepository)) == TENANT_REPOSITORY_METHODS


def test_every_exemption_gives_a_reason():
    assert all(reason.strip() for reason in EXEMPT_REPOSITORIES.values())
