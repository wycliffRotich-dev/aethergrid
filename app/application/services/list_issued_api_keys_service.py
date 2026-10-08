from __future__ import annotations

from app.domain.entities.api_key import ApiKey
from app.domain.exceptions.api_key_not_found_error import (
    ApiKeyNotFoundError,
)
from app.domain.repositories.api_key_repository import (
    ApiKeyRepository,
)
from app.domain.services.key_authorization import (
    authorize_key_view,
)
from app.domain.value_objects.api_key_id import ApiKeyId

MAX_ISSUED_KEYS_RETURNED = 100


class ListIssuedApiKeysService:
    """
    Return the keys issued by a given API key (ADR 0056
    follow-up).

    Loads the issuer first, raising ApiKeyNotFoundError if it
    does not exist, before deciding whether caller may view
    its list -- the same not-found-before-authorization
    ordering RevokeApiKeyService already uses, so a caller
    without rights over a given id still only learns whether
    that id exists, not anything about what it issued.

    Both reads are scoped to the caller's tenant (ADR 0064,
    point 5). An issuer in another tenant is reported
    exactly like a missing one, so the answer cannot reveal
    that it exists.
    """

    def __init__(
        self,
        api_key_repository: ApiKeyRepository,
    ) -> None:
        self._api_key_repository = api_key_repository

    def execute(
        self,
        issuer_id: ApiKeyId,
        caller: ApiKey,
    ) -> list[ApiKey]:
        issuer = self._api_key_repository.get_by_id(
            issuer_id,
            caller.tenant_id,
        )

        if issuer is None:
            raise ApiKeyNotFoundError(issuer_id)

        authorize_key_view(
            caller_scopes=caller.scopes,
            caller_id=caller.id,
            requested_issuer_id=issuer.id,
        )

        return self._api_key_repository.list_issued_by(
            issuer_id,
            caller.tenant_id,
        )[:MAX_ISSUED_KEYS_RETURNED]
