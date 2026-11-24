from __future__ import annotations

import pytest

from app.infrastructure.repositories.in_memory_lease_reclaim_repository import (
    InMemoryLeaseReclaimRepository,
)
from tests.infrastructure.repositories.contract.lease_reclaim_repository_contract import (
    LeaseReclaimRepositoryContract,
)


class TestInMemoryLeaseReclaimRepositoryContract(
    LeaseReclaimRepositoryContract,
):
    """
    Verify the in-memory implementation satisfies the
    LeaseReclaimRepository contract.
    """

    @pytest.fixture
    def repository(self):
        return InMemoryLeaseReclaimRepository()
