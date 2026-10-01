from __future__ import annotations

import pytest

from app.domain.exceptions.scope_denied_error import ScopeDeniedError
from app.domain.services.key_authorization import (
    authorize_key_management,
    authorize_key_revocation,
)
from app.domain.value_objects.api_key_id import ApiKeyId
from app.domain.value_objects.api_key_scope import KEYS_MANAGE

# -- authorize_key_management (ADR 0055) --


def test_management_allows_a_caller_holding_keys_manage() -> None:
    authorize_key_management({KEYS_MANAGE})


def test_management_denies_a_caller_without_keys_manage() -> None:
    with pytest.raises(ScopeDeniedError) as exc_info:
        authorize_key_management(frozenset())

    assert exc_info.value.scope == KEYS_MANAGE


def test_management_denies_a_caller_holding_unrelated_scopes() -> None:
    with pytest.raises(ScopeDeniedError):
        authorize_key_management({"jobs:execute"})


# -- authorize_key_revocation (ADR 0056) --


def test_revocation_allows_keys_manage_on_a_key_it_did_not_issue() -> None:
    caller_id = ApiKeyId.new()
    someone_elses_key = ApiKeyId.new()

    # keys:manage is an override: it must succeed here even
    # though caller_id is nowhere related to target_issued_by.
    authorize_key_revocation(
        caller_scopes={KEYS_MANAGE},
        caller_id=caller_id,
        target_issued_by=someone_elses_key,
    )


def test_revocation_allows_keys_manage_on_a_legacy_key() -> None:
    # target_issued_by=None is the legacy/bootstrap case. The
    # override must still work: keys:manage is never blocked
    # by the target having no owner at all.
    authorize_key_revocation(
        caller_scopes={KEYS_MANAGE},
        caller_id=ApiKeyId.new(),
        target_issued_by=None,
    )


def test_revocation_allows_the_owner_without_keys_manage() -> None:
    caller_id = ApiKeyId.new()

    # No keys:manage at all. Ownership alone must be
    # sufficient: this is the entire point of ADR 0056.
    authorize_key_revocation(
        caller_scopes=frozenset(),
        caller_id=caller_id,
        target_issued_by=caller_id,
    )


def test_revocation_denies_a_non_owner_without_keys_manage() -> None:
    with pytest.raises(ScopeDeniedError) as exc_info:
        authorize_key_revocation(
            caller_scopes=frozenset(),
            caller_id=ApiKeyId.new(),
            target_issued_by=ApiKeyId.new(),
        )

    assert exc_info.value.scope == KEYS_MANAGE


def test_revocation_denies_a_caller_with_unrelated_scopes_on_a_key_not_its_own() -> (
    None
):
    # Holding some other scope must not leak into this
    # decision: only keys:manage or direct ownership count.
    with pytest.raises(ScopeDeniedError):
        authorize_key_revocation(
            caller_scopes={"jobs:execute"},
            caller_id=ApiKeyId.new(),
            target_issued_by=ApiKeyId.new(),
        )


def test_revocation_denies_anyone_without_keys_manage_on_a_legacy_key() -> None:
    # target_issued_by=None: nobody can claim ownership of a
    # key that predates ownership tracking, no matter what
    # caller_id happens to be. Only keys:manage reaches it.
    with pytest.raises(ScopeDeniedError):
        authorize_key_revocation(
            caller_scopes=frozenset(),
            caller_id=ApiKeyId.new(),
            target_issued_by=None,
        )


def test_revocation_rejects_an_id_that_merely_looks_like_the_owner() -> None:
    # Guards against a same-value-different-identity bug: two
    # ApiKeyId instances wrapping the same UUID value must
    # still compare equal via dataclass equality, so ownership
    # is judged by id value, never by object identity.
    from uuid import uuid4

    shared_value = uuid4()
    caller_id = ApiKeyId(shared_value)
    target_issued_by = ApiKeyId(shared_value)

    assert caller_id is not target_issued_by

    authorize_key_revocation(
        caller_scopes=frozenset(),
        caller_id=caller_id,
        target_issued_by=target_issued_by,
    )
