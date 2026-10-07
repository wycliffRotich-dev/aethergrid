from __future__ import annotations

from app.domain.entities.api_key import ApiKey
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.api_key_id import ApiKeyId
from app.domain.value_objects.tenant_id import TenantId


def make_api_key(
    label: str,
    scopes: frozenset[str] = frozenset(),
    issued_by: ApiKeyId | None = None,
    tenant_id: TenantId = DEFAULT_TENANT_ID,
) -> tuple[ApiKey, str]:
    """
    Build an API key for a test.

    Every test key goes through here, so the tenant a test key
    belongs to is chosen in one place. It is the default tenant
    unless a test says otherwise (ADR 0064).
    """
    return ApiKey.issue(
        label=label,
        tenant_id=tenant_id,
        scopes=scopes,
        issued_by=issued_by,
    )
