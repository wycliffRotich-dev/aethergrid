from __future__ import annotations

from collections.abc import Collection

from app.domain.exceptions.scope_denied_error import (
    ScopeDeniedError,
)
from app.domain.value_objects.api_key_id import ApiKeyId
from app.domain.value_objects.api_key_scope import KEYS_MANAGE


def authorize_key_management(scopes: Collection[str]) -> None:
    """
    Decide whether a caller holding scopes may issue a new
    API key (ADR 0055).

    Issuance has no target to compare ownership against, so
    this is a flat check: keys:manage or nothing. There is no
    unscoped fallback, unlike jobs:execute.

    Pure policy: no I/O, no request or framework types.
    """
    if KEYS_MANAGE not in scopes:
        raise ScopeDeniedError(KEYS_MANAGE)


def authorize_key_revocation(
    caller_scopes: Collection[str],
    caller_id: ApiKeyId,
    target_issued_by: ApiKeyId | None,
) -> None:
    """
    Decide whether a caller holding caller_scopes, identified
    by caller_id, may revoke a key whose issued_by field is
    target_issued_by (ADR 0056).

    Two independent paths grant revocation, either is
    sufficient on its own:

    1. The caller holds keys:manage. This is the override: it
       works on any key, owned or not, including one with
       issued_by set to a different key entirely.
    2. The caller is the key that issued the target
       (caller_id == target_issued_by). This is the ownership
       path: a key that provisioned another key may clean up
       what it created, without needing the broader
       keys:manage scope.

    A target with issued_by=None, every key that predates this
    ADR plus every key issued by scripts/issue_api_key.py, has
    no owner, so only path 1 can ever succeed for it. This is
    deliberate: fabricating an owner for a key where none was
    ever recorded would misrepresent the audit trail, not
    improve it.

    Pure policy: no I/O, no request or framework types, no
    repository access. Both caller and target are passed in
    fully resolved; this function makes no decision about how
    to load either one.
    """
    if KEYS_MANAGE in caller_scopes:
        return

    if (
        target_issued_by is not None
        and caller_id == target_issued_by
    ):
        return

    raise ScopeDeniedError(KEYS_MANAGE)


def authorize_key_view(
    caller_scopes: Collection[str],
    caller_id: ApiKeyId,
    requested_issuer_id: ApiKeyId,
) -> None:
    """
    Decide whether a caller holding caller_scopes, identified
    by caller_id, may list the keys issued by requested_issuer_id
    (ADR 0056 follow-up).

    Same two-path shape as authorize_key_revocation: keys:manage
    is an override that can view any key's issued list, or the
    caller may view its own issued list (caller_id ==
    requested_issuer_id), with no scope required at all for that
    case. There is no legacy-key complication here the way
    revocation has one: requested_issuer_id always names a real,
    existing key the caller is asking about, never an optional
    field that might be unset.

    Pure policy: no I/O, no request or framework types, no
    repository access.
    """
    if KEYS_MANAGE in caller_scopes:
        return

    if caller_id == requested_issuer_id:
        return

    raise ScopeDeniedError(KEYS_MANAGE)
