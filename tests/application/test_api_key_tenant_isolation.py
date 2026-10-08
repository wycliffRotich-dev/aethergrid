from __future__ import annotations

import pytest

from app.application.services.authenticate_api_key_service import (
    AuthenticateApiKeyService,
)
from app.application.services.list_issued_api_keys_service import (
    ListIssuedApiKeysService,
)
from app.application.services.revoke_api_key_service import (
    RevokeApiKeyService,
)
from app.domain.exceptions.api_key_not_found_error import (
    ApiKeyNotFoundError,
)
from app.domain.value_objects.api_key_scope import KEYS_MANAGE
from app.domain.value_objects.tenant_id import TenantId
from tests.support.api_keys import (
    RecordingApiKeyRepository,
    make_api_key,
)


@pytest.fixture
def keys():
    return RecordingApiKeyRepository()


@pytest.fixture
def tenant_a():
    return TenantId.new()


@pytest.fixture
def tenant_b():
    return TenantId.new()


def test_revoke_in_another_tenant_is_not_found_even_with_keys_manage(
    keys,
    tenant_a,
    tenant_b,
):
    target, _ = make_api_key(label="target", tenant_id=tenant_a)
    keys.save(target)
    foreign_admin, _ = make_api_key(
        label="foreign-admin",
        scopes=frozenset({KEYS_MANAGE}),
        tenant_id=tenant_b,
    )

    with pytest.raises(ApiKeyNotFoundError):
        RevokeApiKeyService(keys).execute(
            target.id,
            caller=foreign_admin,
        )

    stored = keys.get_by_id(target.id, tenant_a)
    assert stored is not None
    assert stored.is_active()


def test_revoke_in_another_tenant_without_the_scope_is_still_not_found(
    keys,
    tenant_a,
    tenant_b,
):
    # Not-found comes before the scope decision, so a caller
    # without rights in another tenant cannot learn that the
    # key exists by getting a 403 instead of a 404.
    target, _ = make_api_key(label="target", tenant_id=tenant_a)
    keys.save(target)
    foreign_caller, _ = make_api_key(
        label="foreign-caller",
        tenant_id=tenant_b,
    )

    with pytest.raises(ApiKeyNotFoundError):
        RevokeApiKeyService(keys).execute(
            target.id,
            caller=foreign_caller,
        )


def test_list_issued_in_another_tenant_is_not_found_even_with_keys_manage(
    keys,
    tenant_a,
    tenant_b,
):
    issuer, _ = make_api_key(label="issuer", tenant_id=tenant_a)
    keys.save(issuer)
    child, _ = issuer.issue_child(label="child")
    keys.save(child)
    foreign_admin, _ = make_api_key(
        label="foreign-admin",
        scopes=frozenset({KEYS_MANAGE}),
        tenant_id=tenant_b,
    )

    with pytest.raises(ApiKeyNotFoundError):
        ListIssuedApiKeysService(keys).execute(
            issuer.id,
            caller=foreign_admin,
        )


def test_list_issued_in_the_same_tenant_still_works(
    keys,
    tenant_a,
):
    issuer, _ = make_api_key(label="issuer", tenant_id=tenant_a)
    keys.save(issuer)
    child, _ = issuer.issue_child(label="child")
    keys.save(child)

    issued = ListIssuedApiKeysService(keys).execute(
        issuer.id,
        caller=issuer,
    )

    assert [key.id for key in issued] == [child.id]


def test_authentication_returns_the_keys_own_tenant(
    keys,
    tenant_b,
):
    key, raw_key = make_api_key(label="runner", tenant_id=tenant_b)
    keys.save(key)

    caller = AuthenticateApiKeyService(keys).execute(raw_key)

    assert caller.tenant_id == tenant_b
    stored = keys.get_by_id(key.id, tenant_b)
    assert stored is not None
    assert stored.last_used_at is not None
