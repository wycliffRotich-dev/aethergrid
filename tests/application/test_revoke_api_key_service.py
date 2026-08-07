from __future__ import annotations

import pytest

from app.application.services.create_api_key_service import (
    CreateApiKeyService,
)
from app.application.services.revoke_api_key_service import (
    RevokeApiKeyService,
)
from app.domain.exceptions.api_key_not_found_error import (
    ApiKeyNotFoundError,
)
from app.domain.value_objects.api_key_id import ApiKeyId
from app.infrastructure.repositories.in_memory_api_key_repository import (
    InMemoryApiKeyRepository,
)


@pytest.fixture
def repository():
    return InMemoryApiKeyRepository()


def test_revoking_unknown_id_raises_not_found(repository):
    with pytest.raises(ApiKeyNotFoundError):
        RevokeApiKeyService(repository).execute(
            ApiKeyId.new(),
        )


def test_revoke_marks_the_key_inactive(repository):
    issued = CreateApiKeyService(repository).execute(
        label="ci-runner",
    )

    RevokeApiKeyService(repository).execute(issued.id)

    fetched = repository.get_by_id(issued.id)

    assert fetched is not None
    assert fetched.is_active() is False


def test_revoking_twice_is_a_no_op_not_an_error(repository):
    # Idempotent at the application layer even though the
    # domain entity itself raises on a double revoke: a
    # retried request (script rerun, double click) shouldn't
    # surface an error for an operation whose desired end
    # state already holds.
    issued = CreateApiKeyService(repository).execute(
        label="ci-runner",
    )

    RevokeApiKeyService(repository).execute(issued.id)
    RevokeApiKeyService(repository).execute(issued.id)
