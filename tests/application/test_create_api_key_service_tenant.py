from __future__ import annotations

import pytest

from app.application.services.create_api_key_service import (
    CreateApiKeyService,
)
from app.domain.entities.tenant import Tenant
from app.domain.exceptions.tenant_not_found_error import (
    TenantNotFoundError,
)
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.in_memory_api_key_repository import (
    InMemoryApiKeyRepository,
)
from app.infrastructure.repositories.in_memory_tenant_repository import (
    InMemoryTenantRepository,
)
from tests.support.api_keys import make_api_key


@pytest.fixture
def keys():
    return InMemoryApiKeyRepository()


@pytest.fixture
def tenants():
    return InMemoryTenantRepository()


@pytest.fixture
def service(keys, tenants):
    return CreateApiKeyService(keys, tenants)


def test_bootstrap_issuance_places_the_key_in_the_named_tenant(
    service,
    keys,
    tenants,
):
    acme = Tenant.create("acme")
    tenants.save(acme)

    issued = service.execute(label="runner", tenant_id=acme.id)

    stored = keys.get_by_id(issued.id)
    assert stored is not None
    assert stored.tenant_id == acme.id
    assert stored.issued_by is None


def test_an_unknown_tenant_is_rejected_and_nothing_is_saved(
    service,
    keys,
):
    with pytest.raises(TenantNotFoundError):
        service.execute(label="runner", tenant_id=TenantId.new())

    assert keys.list_active() == []


def test_issuance_by_a_key_inherits_the_issuers_tenant(
    service,
    keys,
    tenants,
):
    acme = Tenant.create("acme")
    tenants.save(acme)
    issuer, _ = make_api_key(label="issuer", tenant_id=acme.id)
    keys.save(issuer)

    issued = service.execute(label="child", issuer=issuer)

    stored = keys.get_by_id(issued.id)
    assert stored is not None
    assert stored.tenant_id == acme.id
    assert stored.issued_by == issuer.id


def test_exactly_one_of_issuer_and_tenant_is_required(
    service,
    keys,
    tenants,
):
    acme = Tenant.create("acme")
    tenants.save(acme)
    issuer, _ = make_api_key(label="issuer", tenant_id=acme.id)

    with pytest.raises(ValueError):
        service.execute(label="neither")

    with pytest.raises(ValueError):
        service.execute(label="both", issuer=issuer, tenant_id=acme.id)

    assert keys.list_active() == []
