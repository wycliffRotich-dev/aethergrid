from __future__ import annotations

import pytest

from app.application.services.create_api_key_service import (
    CreateApiKeyService,
)
from app.application.services.revoke_api_key_service import (
    RevokeApiKeyService,
)
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.exceptions.api_key_not_found_error import (
    ApiKeyNotFoundError,
)
from app.domain.value_objects.api_key_id import ApiKeyId
from app.domain.value_objects.api_key_scope import KEYS_MANAGE
from app.infrastructure.repositories.in_memory_api_key_repository import (
    InMemoryApiKeyRepository,
)
from app.infrastructure.repositories.in_memory_tenant_repository import (
    InMemoryTenantRepository,
)
from tests.support.api_keys import make_api_key


@pytest.fixture
def repository():
    return InMemoryApiKeyRepository()


@pytest.fixture
def admin():
    caller, _ = make_api_key(
        label="admin",
        scopes=frozenset({KEYS_MANAGE}),
    )
    return caller


def test_revoking_unknown_id_raises_not_found(repository, admin):
    with pytest.raises(ApiKeyNotFoundError):
        RevokeApiKeyService(repository).execute(
            ApiKeyId.new(),
            caller=admin,
        )


def test_revoke_marks_the_key_inactive(repository, admin):
    issued = CreateApiKeyService(repository, tenant_repository=InMemoryTenantRepository()).execute(
        label="ci-runner", tenant_id=DEFAULT_TENANT_ID,
    )

    RevokeApiKeyService(repository).execute(issued.id, caller=admin)

    fetched = repository.get_by_id(issued.id)

    assert fetched is not None
    assert fetched.is_active() is False


def test_revoking_twice_is_a_no_op_not_an_error(repository, admin):
    # Idempotent at the application layer even though the
    # domain entity itself raises on a double revoke: a
    # retried request (script rerun, double click) shouldn't
    # surface an error for an operation whose desired end
    # state already holds.
    issued = CreateApiKeyService(repository, tenant_repository=InMemoryTenantRepository()).execute(
        label="ci-runner", tenant_id=DEFAULT_TENANT_ID,
    )

    RevokeApiKeyService(repository).execute(issued.id, caller=admin)
    RevokeApiKeyService(repository).execute(issued.id, caller=admin)
