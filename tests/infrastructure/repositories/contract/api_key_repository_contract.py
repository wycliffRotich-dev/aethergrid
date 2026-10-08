from __future__ import annotations

import copy

import pytest

from app.domain.entities.api_key import ApiKey
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.exceptions.api_key_not_found_error import (
    ApiKeyNotFoundError,
)
from app.domain.exceptions.api_key_tenant_conflict_error import (
    ApiKeyTenantConflictError,
)
from app.domain.value_objects.api_key_id import ApiKeyId
from app.domain.value_objects.tenant_id import TenantId
from tests.support.api_keys import make_api_key


class ApiKeyRepositoryContract:
    """
    Shared behavioral contract that every
    ApiKeyRepository implementation must satisfy.
    """

    @pytest.fixture
    def repository(self):
        raise NotImplementedError(
            "Subclasses must provide a `repository` fixture."
        )

    def _make_api_key(self) -> ApiKey:
        api_key, _raw_key = make_api_key(
            label="ci-runner",
        )
        return api_key

    def test_save_and_get_by_id(
        self,
        repository,
    ) -> None:
        api_key = self._make_api_key()

        repository.save(api_key)

        fetched = repository.get_by_id(
            api_key.id,
            DEFAULT_TENANT_ID,
        )

        assert fetched is not None
        assert fetched.id == api_key.id
        assert fetched.key_hash == api_key.key_hash

    def test_get_by_id_returns_none_when_absent(
        self,
        repository,
    ) -> None:
        assert (
            repository.get_by_id(
                ApiKeyId.new(),
                DEFAULT_TENANT_ID,
            )
            is None
        )

    def test_save_and_get_by_hash(
        self,
        repository,
    ) -> None:
        api_key = self._make_api_key()

        repository.save(api_key)

        fetched = repository.get_by_hash_across_tenants(
            api_key.key_hash,
        )

        assert fetched is not None
        assert fetched.id == api_key.id

    def test_get_by_hash_returns_none_when_absent(
        self,
        repository,
    ) -> None:
        assert (
            repository.get_by_hash_across_tenants(
                "not-a-real-hash",
            )
            is None
        )

    def test_save_persists_revocation(
        self,
        repository,
    ) -> None:
        api_key = self._make_api_key()

        repository.save(api_key)

        api_key.revoke()
        repository.save(api_key)

        fetched = repository.get_by_id(
            api_key.id,
            DEFAULT_TENANT_ID,
        )

        assert fetched is not None
        assert fetched.revoked_at is not None

    def test_mark_used_persists_without_reloading_the_entity(
        self,
        repository,
    ) -> None:
        # This is the actual behavior mark_used() exists to
        # provide: recording usage without a load/save round
        # trip through the entity at all.
        api_key = self._make_api_key()

        repository.save(api_key)

        repository.mark_used(
            api_key.id,
            DEFAULT_TENANT_ID,
        )

        fetched = repository.get_by_id(
            api_key.id,
            DEFAULT_TENANT_ID,
        )

        assert fetched is not None
        assert fetched.last_used_at is not None

    def test_mark_used_raises_when_key_does_not_exist(
        self,
        repository,
    ) -> None:
        # deliberately never saved -- the racing-a-revocation
        # case, and it must not silently create a key that
        # looks like it was always there
        with pytest.raises(ApiKeyNotFoundError):
            repository.mark_used(
                ApiKeyId.new(),
                DEFAULT_TENANT_ID,
            )

    def test_scopes_round_trip_by_id_and_by_hash(
        self,
        repository,
    ) -> None:
        api_key, _ = make_api_key(
            label="scoped",
            scopes=frozenset({"jobs:execute"}),
        )

        repository.save(api_key)

        by_id = repository.get_by_id(api_key.id, DEFAULT_TENANT_ID)
        by_hash = repository.get_by_hash_across_tenants(api_key.key_hash)

        assert by_id.scopes == frozenset({"jobs:execute"})
        assert by_hash.scopes == frozenset({"jobs:execute"})

    def test_key_saved_without_scopes_reloads_with_none(
        self,
        repository,
    ) -> None:
        api_key, _ = make_api_key(label="plain")

        repository.save(api_key)

        assert repository.get_by_id(api_key.id, DEFAULT_TENANT_ID).scopes == frozenset()

    def test_issued_by_round_trips_by_id(
        self,
        repository,
    ) -> None:
        issuer = self._make_api_key()
        repository.save(issuer)

        issued, _ = make_api_key(
            label="sub-key",
            issued_by=issuer.id,
        )
        repository.save(issued)

        fetched = repository.get_by_id(issued.id, DEFAULT_TENANT_ID)

        assert fetched is not None
        assert fetched.issued_by == issuer.id

    def test_key_saved_without_issued_by_reloads_with_none(
        self,
        repository,
    ) -> None:
        api_key = self._make_api_key()

        repository.save(api_key)

        assert repository.get_by_id(api_key.id, DEFAULT_TENANT_ID).issued_by is None

    def test_list_issued_by_returns_keys_with_matching_issuer(
        self,
        repository,
    ) -> None:
        issuer = self._make_api_key()
        repository.save(issuer)

        child_one, _ = make_api_key(
            label="child-one", issued_by=issuer.id
        )
        child_two, _ = make_api_key(
            label="child-two", issued_by=issuer.id
        )
        unrelated = self._make_api_key()
        repository.save(child_one)
        repository.save(child_two)
        repository.save(unrelated)

        issued_ids = {
            api_key.id
            for api_key in repository.list_issued_by(issuer.id, DEFAULT_TENANT_ID)
        }

        assert issued_ids == {child_one.id, child_two.id}
        assert unrelated.id not in issued_ids

    def test_list_issued_by_includes_revoked_keys(
        self,
        repository,
    ) -> None:
        issuer = self._make_api_key()
        repository.save(issuer)

        child, _ = make_api_key(
            label="revoked-child", issued_by=issuer.id
        )
        child.revoke()
        repository.save(child)

        issued_ids = {
            api_key.id
            for api_key in repository.list_issued_by(issuer.id, DEFAULT_TENANT_ID)
        }

        assert child.id in issued_ids

    def test_list_issued_by_returns_empty_for_a_key_with_no_children(
        self,
        repository,
    ) -> None:
        issuer = self._make_api_key()
        repository.save(issuer)

        assert repository.list_issued_by(issuer.id, DEFAULT_TENANT_ID) == []

    def test_tenant_round_trips(
        self,
        repository,
    ) -> None:
        api_key = self._make_api_key()

        repository.save(api_key)

        fetched = repository.get_by_id(api_key.id, DEFAULT_TENANT_ID)

        assert fetched is not None
        assert fetched.tenant_id == api_key.tenant_id
        assert fetched.tenant_id == DEFAULT_TENANT_ID

    @pytest.fixture
    def second_tenant_id(self) -> TenantId:
        """
        A tenant other than the default one. Backends whose
        storage enforces tenant rows override this to create
        the tenant first.
        """
        return TenantId.new()

    def test_get_by_id_in_another_tenant_returns_none(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        api_key = self._make_api_key()
        repository.save(api_key)

        assert (
            repository.get_by_id(api_key.id, second_tenant_id)
            is None
        )

    def test_mark_used_in_another_tenant_raises_and_changes_nothing(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        api_key = self._make_api_key()
        repository.save(api_key)

        with pytest.raises(ApiKeyNotFoundError):
            repository.mark_used(api_key.id, second_tenant_id)

        fetched = repository.get_by_id(
            api_key.id,
            DEFAULT_TENANT_ID,
        )

        assert fetched is not None
        assert fetched.last_used_at is None

    def test_list_issued_by_in_another_tenant_is_empty(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        issuer = self._make_api_key()
        repository.save(issuer)

        child, _ = make_api_key(
            label="child",
            issued_by=issuer.id,
        )
        repository.save(child)

        assert (
            repository.list_issued_by(issuer.id, second_tenant_id)
            == []
        )

    def test_get_by_hash_across_tenants_finds_a_key_in_any_tenant(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        api_key, _ = make_api_key(
            label="other-tenant",
            tenant_id=second_tenant_id,
        )
        repository.save(api_key)

        fetched = repository.get_by_hash_across_tenants(
            api_key.key_hash,
        )

        assert fetched is not None
        assert fetched.id == api_key.id
        assert fetched.tenant_id == second_tenant_id

    def test_save_in_another_tenant_raises_and_changes_nothing(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        api_key = self._make_api_key()
        repository.save(api_key)

        # A separate object with the same id, claiming another
        # tenant and a revocation. Saving it is reported as a
        # conflict and must not move or revoke the stored key.
        impostor = copy.deepcopy(api_key)
        impostor.tenant_id = second_tenant_id
        impostor.revoke()

        with pytest.raises(ApiKeyTenantConflictError):
            repository.save(impostor)

        fetched = repository.get_by_id(
            api_key.id,
            DEFAULT_TENANT_ID,
        )

        assert fetched is not None
        assert fetched.tenant_id == DEFAULT_TENANT_ID
        assert fetched.revoked_at is None
