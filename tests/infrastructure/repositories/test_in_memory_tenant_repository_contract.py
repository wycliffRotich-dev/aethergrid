from __future__ import annotations

import pytest

from app.infrastructure.repositories.in_memory_tenant_repository import (
    InMemoryTenantRepository,
)
from tests.infrastructure.repositories.contract.tenant_repository_contract import (
    TenantRepositoryContract,
)


class TestInMemoryTenantRepositoryContract(
    TenantRepositoryContract,
):
    @pytest.fixture
    def repository(self):
        return InMemoryTenantRepository()
