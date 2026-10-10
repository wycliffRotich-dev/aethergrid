from __future__ import annotations

import pytest

from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from tests.infrastructure.repositories.contract.job_repository_tenant_contract import (
    JobRepositoryTenantContract,
)


class TestInMemoryJobRepositoryTenant(JobRepositoryTenantContract):
    @pytest.fixture
    def repository(self):
        return InMemoryJobRepository()
