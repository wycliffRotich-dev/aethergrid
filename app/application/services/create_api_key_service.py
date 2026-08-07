from __future__ import annotations

from dataclasses import dataclass

from app.domain.entities.api_key import ApiKey
from app.domain.repositories.api_key_repository import (
    ApiKeyRepository,
)
from app.domain.value_objects.api_key_id import ApiKeyId


@dataclass(slots=True)
class IssuedApiKey:
    """
    The result of issuing a new API key.

    plaintext_key is populated only here, on the issuance
    response -- it is never persisted and cannot be recovered
    once this response is returned.
    """

    id: ApiKeyId
    label: str
    plaintext_key: str


class CreateApiKeyService:
    """
    Issues a new API key and persists it.
    """

    def __init__(
        self,
        api_key_repository: ApiKeyRepository,
    ) -> None:
        self._api_key_repository = api_key_repository

    def execute(
        self,
        label: str,
    ) -> IssuedApiKey:
        api_key, raw_key = ApiKey.issue(
            label=label,
        )

        self._api_key_repository.save(
            api_key,
        )

        return IssuedApiKey(
            id=api_key.id,
            label=api_key.label,
            plaintext_key=raw_key,
        )
