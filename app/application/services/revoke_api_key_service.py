from __future__ import annotations

from app.domain.entities.api_key import ApiKey
from app.domain.exceptions.api_key_already_revoked_error import (
    ApiKeyAlreadyRevokedError,
)
from app.domain.exceptions.api_key_not_found_error import (
    ApiKeyNotFoundError,
)
from app.domain.repositories.api_key_repository import (
    ApiKeyRepository,
)
from app.domain.services.key_authorization import (
    authorize_key_revocation,
)
from app.domain.value_objects.api_key_id import ApiKeyId


class RevokeApiKeyService:
    """
    Revokes an existing API key.

    Authorization lives here rather than at the route (ADR
    0056), a deliberate departure from every other scope gate
    in this codebase, which decides at the route before
    reaching the service. Deciding whether this caller may
    revoke this specific target requires the target's
    issued_by, a fact that does not exist until the target is
    loaded, and only this service currently loads it. The
    decision itself stays a pure domain function with no I/O;
    only which layer calls it has moved.
    """

    def __init__(
        self,
        api_key_repository: ApiKeyRepository,
    ) -> None:
        self._api_key_repository = api_key_repository

    def execute(
        self,
        api_key_id: ApiKeyId,
        caller: ApiKey,
    ) -> None:
        # Scoped to the caller's tenant inside the lookup, so
        # a key in another tenant raises the same not-found
        # as a missing id, before any scope decision can
        # answer 403 and reveal that it exists (ADR 0064,
        # point 5).
        api_key = self._api_key_repository.get_by_id(
            api_key_id,
            caller.tenant_id,
        )

        if api_key is None:
            raise ApiKeyNotFoundError(api_key_id)

        authorize_key_revocation(
            caller_scopes=caller.scopes,
            caller_id=caller.id,
            target_issued_by=api_key.issued_by,
        )

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
