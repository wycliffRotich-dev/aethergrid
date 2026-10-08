from __future__ import annotations

import inspect
import typing
from abc import ABC, abstractmethod

import pytest

from app.domain.entities.api_key import ApiKey
from app.domain.repositories.api_key_repository import (
    ApiKeyRepository,
)
from app.domain.value_objects.tenant_id import TenantId

# Repositories already held to ADR 0064, point 4. A repository
# joins this list in the same change that scopes it.
SCOPED_REPOSITORIES = [ApiKeyRepository]

# Entity types that carry their own tenant_id, so a method
# that takes one is scoped by that entity.
TENANT_CARRYING_ENTITIES = (ApiKey,)

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
