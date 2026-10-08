from __future__ import annotations

from app.domain.entities.api_key import ApiKey
from app.domain.exceptions.api_key_not_found_error import (
    ApiKeyNotFoundError,
)
from app.domain.exceptions.api_key_tenant_conflict_error import (
    ApiKeyTenantConflictError,
)
from app.domain.repositories.api_key_repository import (
    ApiKeyRepository,
)
from app.domain.value_objects.api_key_id import ApiKeyId
from app.domain.value_objects.tenant_id import TenantId


class InMemoryApiKeyRepository(
    ApiKeyRepository,
):
    """
    In-memory implementation of the ApiKeyRepository.

    Every tenant-scoped lookup matches the tenant in the same
    condition as the id, so a key that belongs to another
    tenant is indistinguishable from one that does not exist
    (ADR 0064, point 5).
    """

    def __init__(
        self,
    ) -> None:
        self._api_keys: dict[str, ApiKey] = {}

    def save(
        self,
        api_key: ApiKey,
    ) -> None:
        existing = self._api_keys.get(str(api_key.id))

        # Same rule as the Postgres upsert: a save never
        # touches a key held by another tenant, and never
        # moves a key between tenants. It is reported, not
        # ignored.
        if (
            existing is not None
            and existing.tenant_id != api_key.tenant_id
        ):
            raise ApiKeyTenantConflictError(
                f"api key {api_key.id} belongs to another tenant"
            )

        self._api_keys[
            str(api_key.id)
        ] = api_key

    def mark_used(
        self,
        api_key_id: ApiKeyId,
        tenant_id: TenantId,
    ) -> None:
        api_key = self.get_by_id(
            api_key_id,
            tenant_id,
        )

        if api_key is None:
            raise ApiKeyNotFoundError(api_key_id)

        api_key.mark_used()

    def get_by_id(
        self,
        api_key_id: ApiKeyId,
        tenant_id: TenantId,
    ) -> ApiKey | None:
        api_key = self._api_keys.get(
            str(api_key_id),
        )

        if api_key is None or api_key.tenant_id != tenant_id:
            return None

        return api_key

    def get_by_hash_across_tenants(
        self,
        key_hash: str,
    ) -> ApiKey | None:
        for api_key in self._api_keys.values():
            if api_key.key_hash == key_hash:
                return api_key

        return None

    def list_issued_by(
        self,
        issuer_id: ApiKeyId,
        tenant_id: TenantId,
    ) -> list[ApiKey]:
        return [
            api_key
            for api_key in self._api_keys.values()
            if api_key.issued_by == issuer_id
            and api_key.tenant_id == tenant_id
        ]
