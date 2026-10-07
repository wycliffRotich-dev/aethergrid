from __future__ import annotations

from dataclasses import dataclass

from app.domain.entities.api_key import ApiKey
from app.domain.exceptions.tenant_not_found_error import (
    TenantNotFoundError,
)
from app.domain.repositories.api_key_repository import (
    ApiKeyRepository,
)
from app.domain.repositories.tenant_repository import (
    TenantRepository,
)
from app.domain.value_objects.api_key_id import ApiKeyId
from app.domain.value_objects.tenant_id import TenantId


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
    scopes: frozenset[str] = frozenset()


class CreateApiKeyService:
    """
    Issues a new API key and persists it.

    A key always belongs to a tenant (ADR 0064), and exactly one
    of two things decides which:

    - issuer: an authenticated key is issuing the new one. The
      new key takes the issuer's tenant and records the issuer
      (ADR 0056), and no caller can choose a different tenant.
      This is the path behind POST /api-keys.
    - tenant_id: the bootstrap path, run with direct repository
      access and no authenticated caller
      (scripts/issue_api_key.py). The tenant must already exist.

    scopes defaults to empty (ADR 0054). Unknown scopes are
    rejected by ApiKey.issue(), so nothing is persisted for a
    mistyped scope.
    """

    def __init__(
        self,
        api_key_repository: ApiKeyRepository,
        tenant_repository: TenantRepository,
    ) -> None:
        self._api_key_repository = api_key_repository
        self._tenant_repository = tenant_repository

    def execute(
        self,
        label: str,
        scopes: frozenset[str] = frozenset(),
        issuer: ApiKey | None = None,
        tenant_id: TenantId | None = None,
    ) -> IssuedApiKey:
        if (issuer is None) == (tenant_id is None):
            raise ValueError(
                "exactly one of issuer and tenant_id is required"
            )

        if issuer is not None:
            api_key, raw_key = issuer.issue_child(
                label=label,
                scopes=scopes,
            )
        else:
            if self._tenant_repository.get_by_id(tenant_id) is None:
                raise TenantNotFoundError(
                    f"tenant {tenant_id} does not exist"
                )
            api_key, raw_key = ApiKey.issue(
                label=label,
                tenant_id=tenant_id,
                scopes=scopes,
            )

        self._api_key_repository.save(
            api_key,
        )

        return IssuedApiKey(
            id=api_key.id,
            label=api_key.label,
            plaintext_key=raw_key,
            scopes=api_key.scopes,
        )
