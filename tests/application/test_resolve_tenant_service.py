from __future__ import annotations

import pytest

from app.application.services.resolve_tenant_service import (
    ResolveTenantService,
)
from app.domain.entities.tenant import (
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_NAME,
    Tenant,
)
from app.domain.exceptions.tenant_already_exists_error import (
    TenantAlreadyExistsError,
)
from app.domain.exceptions.tenant_not_found_error import (
    TenantNotFoundError,
)
from app.infrastructure.repositories.in_memory_tenant_repository import (
    InMemoryTenantRepository,
)

# ADR 0090: the key script reaches tenants through this service.


class BlindTenantRepository(InMemoryTenantRepository):
    """Misses every name lookup, as an operator racing us would."""

    def get_by_name(self, name: str) -> Tenant | None:
        return None


@pytest.fixture
def tenants() -> InMemoryTenantRepository:
    return InMemoryTenantRepository()


@pytest.fixture
def service(tenants: InMemoryTenantRepository) -> ResolveTenantService:
    return ResolveTenantService(tenants)


def test_an_existing_tenant_is_returned_by_name(
    service: ResolveTenantService,
    tenants: InMemoryTenantRepository,
) -> None:
    acme = Tenant.create("acme")
    tenants.save(acme)

    resolved = service.execute("acme")

    assert resolved.tenant.id == acme.id
    assert resolved.created is False


def test_the_default_tenant_resolves_by_its_name(
    service: ResolveTenantService,
) -> None:
    resolved = service.execute(DEFAULT_TENANT_NAME)

    assert resolved.tenant.id == DEFAULT_TENANT_ID
    assert resolved.created is False


def test_a_missing_tenant_is_refused_and_not_created(
    service: ResolveTenantService,
    tenants: InMemoryTenantRepository,
) -> None:
    with pytest.raises(TenantNotFoundError, match="acme"):
        service.execute("acme")

    assert tenants.get_by_name("acme") is None


def test_a_missing_tenant_is_created_when_asked(
    service: ResolveTenantService,
    tenants: InMemoryTenantRepository,
) -> None:
    resolved = service.execute("acme", create_if_missing=True)

    assert resolved.created is True
    assert resolved.tenant.name == "acme"
    stored = tenants.get_by_name("acme")
    assert stored is not None
    assert stored.id == resolved.tenant.id


def test_creating_again_returns_the_same_tenant_and_says_it_is_not_new(
    service: ResolveTenantService,
) -> None:
    first = service.execute("acme", create_if_missing=True)
    second = service.execute("acme", create_if_missing=True)

    assert second.tenant.id == first.tenant.id
    assert first.created is True
    assert second.created is False


def test_the_name_is_trimmed_for_lookup_and_creation(
    service: ResolveTenantService,
    tenants: InMemoryTenantRepository,
) -> None:
    acme = Tenant.create("acme")
    tenants.save(acme)

    found = service.execute("  acme ")

    assert found.tenant.id == acme.id
    assert found.created is False

    resolved = service.execute("  newco\t", create_if_missing=True)

    assert resolved.created is True
    assert resolved.tenant.name == "newco"
    assert tenants.get_by_name("newco") is not None


def test_names_are_matched_with_case(
    service: ResolveTenantService,
    tenants: InMemoryTenantRepository,
) -> None:
    acme = Tenant.create("acme")
    tenants.save(acme)

    with pytest.raises(TenantNotFoundError):
        service.execute("Acme")

    other = service.execute("Acme", create_if_missing=True)

    assert other.created is True
    assert other.tenant.id != acme.id


@pytest.mark.parametrize("create_if_missing", [False, True])
@pytest.mark.parametrize("name", ["", "   "])
def test_a_blank_name_is_refused_in_both_modes(
    service: ResolveTenantService,
    name: str,
    create_if_missing: bool,
) -> None:
    with pytest.raises(ValueError, match="tenant name"):
        service.execute(name, create_if_missing=create_if_missing)


def test_a_name_taken_in_the_meantime_is_reported_not_hidden() -> None:
    tenants = BlindTenantRepository()
    tenants.save(Tenant.create("acme"))
    service = ResolveTenantService(tenants)

    with pytest.raises(TenantAlreadyExistsError):
        service.execute("acme", create_if_missing=True)
