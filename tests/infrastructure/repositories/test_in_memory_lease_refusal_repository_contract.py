from __future__ import annotations

import pytest

from app.infrastructure.repositories.in_memory_lease_refusal_repository import (
    InMemoryLeaseRefusalRepository,
)
from tests.infrastructure.repositories.contract.lease_refusal_repository_contract import (
    LeaseRefusalRepositoryContract,
)


class TestInMemoryLeaseRefusalRepositoryContract(
    LeaseRefusalRepositoryContract,
):
    """
    Verify the in-memory implementation satisfies the
    LeaseRefusalRepository contract.
    """

    @pytest.fixture
    def repository(self):
        return InMemoryLeaseRefusalRepository()
