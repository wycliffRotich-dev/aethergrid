from __future__ import annotations

import pytest

from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from tests.infrastructure.repositories.contract.job_repository_save_if_unchanged_contract import (
    JobRepositorySaveIfUnchangedContract,
)


class TestInMemoryJobRepositorySaveIfUnchanged(
    JobRepositorySaveIfUnchangedContract
):
    @pytest.fixture
    def repository(self) -> InMemoryJobRepository:
        return InMemoryJobRepository()
