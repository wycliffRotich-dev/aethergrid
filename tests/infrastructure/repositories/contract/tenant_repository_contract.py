from __future__ import annotations

import pytest

from app.domain.entities.tenant import (
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_NAME,
    Tenant,
)
from app.domain.exceptions.tenant_already_exists_error import (
    TenantAlreadyExistsError,
)
from app.domain.value_objects.tenant_id import TenantId


class TenantRepositoryContract:
    """
    Behaviour every TenantRepository must share. A subclass
    supplies a `repository` fixture that starts in the same
    state on every backend: only the default tenant exists.
    """

    def test_a_fresh_repository_holds_the_default_tenant(
        self,
        repository,
    ):
        found = repository.get_by_id(DEFAULT_TENANT_ID)

        assert found is not None
        assert found.id == DEFAULT_TENANT_ID
        assert found.name == DEFAULT_TENANT_NAME
        assert repository.get_by_name(DEFAULT_TENANT_NAME) == found

    def test_a_saved_tenant_round_trips_by_id_and_by_name(
        self,
        repository,
    ):
        tenant = Tenant.create("acme")

        repository.save(tenant)

        assert repository.get_by_id(tenant.id) == tenant
        assert repository.get_by_name("acme") == tenant

    def test_an_unknown_id_returns_none(self, repository):
        assert repository.get_by_id(TenantId.new()) is None

    def test_an_unknown_name_returns_none(self, repository):
        assert repository.get_by_name("nobody") is None

    def test_saving_the_same_tenant_twice_is_a_no_op(
        self,
        repository,
    ):
        tenant = Tenant.create("acme")

        repository.save(tenant)
        repository.save(tenant)

        assert repository.get_by_id(tenant.id) == tenant

    def test_a_name_held_by_another_tenant_is_rejected(
        self,
        repository,
    ):
        first = Tenant.create("acme")
        repository.save(first)

        with pytest.raises(TenantAlreadyExistsError):
            repository.save(Tenant.create("acme"))

        assert repository.get_by_name("acme") == first

    def test_an_existing_id_under_a_different_name_is_rejected(
        self,
        repository,
    ):
        first = Tenant.create("acme")
        repository.save(first)

        with pytest.raises(TenantAlreadyExistsError):
            repository.save(Tenant(id=first.id, name="renamed"))

        assert repository.get_by_id(first.id) == first
        assert repository.get_by_name("renamed") is None
