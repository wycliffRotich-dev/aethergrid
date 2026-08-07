from __future__ import annotations

from app.domain.exceptions.api_key_already_revoked_error import (
    ApiKeyAlreadyRevokedError,
)
from app.domain.exceptions.api_key_not_found_error import (
    ApiKeyNotFoundError,
)
from app.domain.repositories.api_key_repository import (
    ApiKeyRepository,
)
from app.domain.value_objects.api_key_id import ApiKeyId


class RevokeApiKeyService:
    """
    Revokes an existing API key.
    """

    def __init__(
        self,
        api_key_repository: ApiKeyRepository,
    ) -> None:
        self._api_key_repository = api_key_repository

    def execute(
        self,
        api_key_id: ApiKeyId,
    ) -> None:
        api_key = self._api_key_repository.get_by_id(
            api_key_id,
        )

        if api_key is None:
            raise ApiKeyNotFoundError(api_key_id)

        try:
            api_key.revoke()
        except ApiKeyAlreadyRevokedError:
            # Revoking an already-revoked key is a no-op from
            # the caller's perspective: the end state they
            # wanted (key is dead) already holds. Re-raising
            # would make revocation non-idempotent, the wrong
            # property for a security operation a script or a
            # nervous human might retry.
            return

        self._api_key_repository.save(
            api_key,
        )
