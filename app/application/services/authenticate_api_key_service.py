from __future__ import annotations

from app.domain.entities.api_key import ApiKey
from app.domain.repositories.api_key_repository import (
    ApiKeyRepository,
)


class InvalidApiKeyError(Exception):
    """
    Raised when a presented credential is malformed, unknown,
    or revoked.

    Deliberately not a DomainError subclass: this represents
    an authentication failure on an incoming request, not a
    violation of one of ApiKey's own invariants. The domain
    entity itself never gets far enough to have an opinion --
    an unknown key never resolves to an ApiKey at all.
    """


class AuthenticateApiKeyService:
    """
    Verifies a raw credential presented on an incoming request
    and returns the authenticated ApiKey if it is valid, or
    raises InvalidApiKeyError.
    """

    def __init__(
        self,
        api_key_repository: ApiKeyRepository,
    ) -> None:
        self._api_key_repository = api_key_repository

    def execute(
        self,
        raw_key: str,
    ) -> ApiKey:
        if not raw_key:
            raise InvalidApiKeyError(
                "no credential presented",
            )

        key_hash = ApiKey.hash_secret(raw_key)

        api_key = self._api_key_repository.get_by_hash(
            key_hash,
        )

        if api_key is None or not api_key.is_active():
            # Deliberately the same error for "unknown key" and
            # "revoked key." Distinguishing them in the
            # response would let a caller enumerate which keys
            # exist versus which are merely wrong, information
            # a 401 must never leak.
            raise InvalidApiKeyError(
                "invalid or revoked credential",
            )

        # Repository-level shortcut, not a domain round trip --
        # mirrors RenewLeaseService calling
        # lease_repository.renew() directly rather than loading
        # the Lease, mutating it, and saving it back. This runs
        # on every authenticated request, so skipping the extra
        # load/save is the same tradeoff already made for lease
        # renewal on its own hot path.
        self._api_key_repository.mark_used(
            api_key.id,
        )

        return api_key
