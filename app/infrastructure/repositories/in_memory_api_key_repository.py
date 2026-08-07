from __future__ import annotations

from app.domain.entities.api_key import ApiKey
from app.domain.exceptions.api_key_not_found_error import (
    ApiKeyNotFoundError,
)
from app.domain.repositories.api_key_repository import (
    ApiKeyRepository,
)
from app.domain.value_objects.api_key_id import ApiKeyId


class InMemoryApiKeyRepository(
    ApiKeyRepository,
):
    """
    In-memory implementation of the ApiKeyRepository.
    """

    def __init__(
        self,
    ) -> None:
        self._api_keys: dict[str, ApiKey] = {}

    def save(
        self,
        api_key: ApiKey,
    ) -> None:
        self._api_keys[
            str(api_key.id)
        ] = api_key

    def mark_used(
        self,
        api_key_id: ApiKeyId,
    ) -> None:
        api_key = self._api_keys.get(
            str(api_key_id),
        )

        if api_key is None:
            raise ApiKeyNotFoundError(api_key_id)

        api_key.mark_used()

    def get_by_id(
        self,
        api_key_id: ApiKeyId,
    ) -> ApiKey | None:
        return self._api_keys.get(
            str(api_key_id),
        )

    def get_by_hash(
        self,
        key_hash: str,
    ) -> ApiKey | None:
        for api_key in self._api_keys.values():
            if api_key.key_hash == key_hash:
                return api_key

        return None

    def list_active(
        self,
    ) -> list[ApiKey]:
        return [
            api_key
            for api_key in self._api_keys.values()
            if api_key.is_active()
        ]
