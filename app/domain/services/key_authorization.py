from __future__ import annotations

from collections.abc import Collection

from app.domain.exceptions.scope_denied_error import (
    ScopeDeniedError,
)
from app.domain.value_objects.api_key_scope import KEYS_MANAGE


def authorize_key_management(scopes: Collection[str]) -> None:
    """
    Decide whether a caller holding scopes may issue or
    revoke API keys (ADR 0055).

    Unlike jobs:execute, there is no unscoped path here: a
    key without keys:manage cannot manage keys at all, full
    stop.

    Pure policy: no I/O, no request or framework types.
    """
    if KEYS_MANAGE not in scopes:
        raise ScopeDeniedError(KEYS_MANAGE)
