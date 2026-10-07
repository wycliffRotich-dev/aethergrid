from __future__ import annotations

import pytest
from psycopg_pool import ConnectionPool

from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.infrastructure.repositories.postgres_tenant_repository import (
    PostgresTenantRepository,
)
from tests.infrastructure.repositories.contract.tenant_repository_contract import (
    TenantRepositoryContract,
)


@pytest.fixture(scope="session")
def pool(test_database_url):
    test_pool = ConnectionPool(
        test_database_url,
        min_size=1,
        max_size=5,
        open=True,
        kwargs={"autocommit": True},
    )
    yield test_pool
    test_pool.close()


class TestPostgresTenantRepositoryContract(
    TenantRepositoryContract,
):
    """
    Resets to the state schema.sql creates: only the default
    tenant. A plain TRUNCATE would remove that row, and would
    fail outright once other tables reference tenants, so every
    other tenant is deleted instead.
    """

    @pytest.fixture
    def repository(self, pool):
        with pool.connection() as conn:
            conn.execute(
                "DELETE FROM tenants WHERE id <> %s",
                (str(DEFAULT_TENANT_ID),),
            )

        return PostgresTenantRepository(pool)
