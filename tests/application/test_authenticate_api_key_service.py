from __future__ import annotations

import pytest

from app.application.services.authenticate_api_key_service import (
    AuthenticateApiKeyService,
    InvalidApiKeyError,
)
from app.application.services.create_api_key_service import (
    CreateApiKeyService,
)
from app.application.services.revoke_api_key_service import (
    RevokeApiKeyService,
)
from app.infrastructure.repositories.in_memory_api_key_repository import (
    InMemoryApiKeyRepository,
)


@pytest.fixture
def repository():
    return InMemoryApiKeyRepository()


def test_authenticates_a_freshly_issued_key(repository):
    issued = CreateApiKeyService(repository).execute(
        label="ci-runner",
    )

    caller = AuthenticateApiKeyService(repository).execute(
        issued.plaintext_key,
    )

    assert caller.id == issued.id


def test_rejects_unknown_key(repository):
    with pytest.raises(InvalidApiKeyError):
        AuthenticateApiKeyService(repository).execute(
            "not-a-real-key",
        )


def test_rejects_empty_credential(repository):
    with pytest.raises(InvalidApiKeyError):
        AuthenticateApiKeyService(repository).execute("")


def test_rejects_revoked_key(repository):
    issued = CreateApiKeyService(repository).execute(
        label="ci-runner",
    )

    RevokeApiKeyService(repository).execute(issued.id)

    with pytest.raises(InvalidApiKeyError):
        AuthenticateApiKeyService(repository).execute(
            issued.plaintext_key,
        )


def test_successful_auth_updates_last_used(repository):
    issued = CreateApiKeyService(repository).execute(
        label="ci-runner",
    )

    AuthenticateApiKeyService(repository).execute(
        issued.plaintext_key,
    )

    fetched = repository.get_by_id(issued.id)

    assert fetched is not None
    assert fetched.last_used_at is not None
