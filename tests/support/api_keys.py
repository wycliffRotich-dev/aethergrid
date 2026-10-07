from __future__ import annotations

from app.domain.entities.api_key import ApiKey
from app.domain.value_objects.api_key_id import ApiKeyId


def make_api_key(
    label: str,
    scopes: frozenset[str] = frozenset(),
    issued_by: ApiKeyId | None = None,
) -> tuple[ApiKey, str]:
    """
    Build an API key for a test.

    Every test key goes through here so that the tenant a test
    key belongs to is chosen in one place. ADR 0064 makes the
    tenant a required part of a key, and a test that cares which
    tenant it uses will say so through this helper.
    """
    return ApiKey.issue(
        label=label,
        scopes=scopes,
        issued_by=issued_by,
    )
