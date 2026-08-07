from __future__ import annotations

import pytest

from app.application.services.create_api_key_service import (
    CreateApiKeyService,
)
from app.infrastructure.repositories.in_memory_api_key_repository import (
    InMemoryApiKeyRepository,
)


@pytest.fixture
def repository():
    return InMemoryApiKeyRepository()


def test_execute_returns_plaintext_key_and_persists_the_entity(
    repository,
):
    issued = CreateApiKeyService(repository).execute(
        label="ci-runner",
    )

    fetched = repository.get_by_id(issued.id)

    assert fetched is not None
    assert fetched.key_hash != issued.plaintext_key
