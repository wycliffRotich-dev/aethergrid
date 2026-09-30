from __future__ import annotations

import pytest

from app.domain.entities.api_key import ApiKey
from app.domain.exceptions.api_key_already_revoked_error import (
    ApiKeyAlreadyRevokedError,
)


def test_issue_returns_distinct_plaintext_and_hash():
    api_key, raw_key = ApiKey.issue(label="ci-runner")

    assert api_key.key_hash != raw_key
    assert api_key.key_hash == ApiKey.hash_secret(raw_key)


def test_issue_rejects_empty_label():
    with pytest.raises(ValueError):
        ApiKey.issue(label="")


def test_issue_rejects_whitespace_only_label():
    with pytest.raises(ValueError):
        ApiKey.issue(label="   ")


def test_two_issued_keys_never_collide():
    first, first_raw = ApiKey.issue(label="a")
    second, second_raw = ApiKey.issue(label="b")

    assert first_raw != second_raw
    assert first.key_hash != second.key_hash


def test_newly_issued_key_is_active():
    api_key, _ = ApiKey.issue(label="ci-runner")

    assert api_key.is_active() is True
    assert api_key.revoked_at is None


def test_revoke_sets_revoked_at_and_deactivates():
    api_key, _ = ApiKey.issue(label="ci-runner")

    api_key.revoke()

    assert api_key.is_active() is False
    assert api_key.revoked_at is not None


def test_revoking_twice_raises():
    api_key, _ = ApiKey.issue(label="ci-runner")
    api_key.revoke()

    with pytest.raises(ApiKeyAlreadyRevokedError):
        api_key.revoke()


def test_mark_used_sets_timestamp():
    api_key, _ = ApiKey.issue(label="ci-runner")

    assert api_key.last_used_at is None

    api_key.mark_used()

    assert api_key.last_used_at is not None


def test_issue_defaults_to_no_scopes() -> None:
    api_key, _ = ApiKey.issue(label="plain")

    assert api_key.scopes == frozenset()
    assert not api_key.has_scope("jobs:execute")


def test_issue_grants_only_the_requested_scopes() -> None:
    api_key, _ = ApiKey.issue(
        label="runner",
        scopes=frozenset({"jobs:execute"}),
    )

    assert api_key.has_scope("jobs:execute")
    assert not api_key.has_scope("anything:else")


def test_issue_coerces_scopes_to_frozenset() -> None:
    api_key, _ = ApiKey.issue(
        label="runner",
        scopes={"jobs:execute"},  # type: ignore[arg-type]
    )

    assert isinstance(api_key.scopes, frozenset)
