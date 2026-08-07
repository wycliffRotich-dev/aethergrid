from __future__ import annotations

import pytest

from app.infrastructure.repositories.in_memory_api_key_repository import (
    InMemoryApiKeyRepository,
)
from tests.infrastructure.repositories.contract.api_key_repository_contract import (
    ApiKeyRepositoryContract,
)


class TestInMemoryApiKeyRepositoryContract(
    ApiKeyRepositoryContract,
):
    """
    Verify the in-memory implementation satisfies
    the ApiKeyRepository contract.
    """

    @pytest.fixture
    def repository(self):
        return InMemoryApiKeyRepository()
