from __future__ import annotations

import pytest

from app.domain.entities.api_key import ApiKey
from app.domain.exceptions.api_key_not_found_error import (
    ApiKeyNotFoundError,
)
from app.domain.value_objects.api_key_id import ApiKeyId


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
        api_key, _raw_key = ApiKey.issue(
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
            )
            is None
        )

    def test_save_and_get_by_hash(
        self,
        repository,
    ) -> None:
        api_key = self._make_api_key()

        repository.save(api_key)

        fetched = repository.get_by_hash(
            api_key.key_hash,
        )

        assert fetched is not None
        assert fetched.id == api_key.id

    def test_get_by_hash_returns_none_when_absent(
        self,
        repository,
    ) -> None:
        assert (
            repository.get_by_hash(
                "not-a-real-hash",
            )
            is None
        )

    def test_list_active_excludes_revoked_keys(
        self,
        repository,
    ) -> None:
        active_key = self._make_api_key()
        revoked_key = self._make_api_key()
        revoked_key.revoke()

        repository.save(active_key)
        repository.save(revoked_key)

        active_ids = {
            api_key.id
            for api_key in repository.list_active()
        }

        assert active_key.id in active_ids
        assert revoked_key.id not in active_ids

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
        )

        fetched = repository.get_by_id(
            api_key.id,
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
            )
