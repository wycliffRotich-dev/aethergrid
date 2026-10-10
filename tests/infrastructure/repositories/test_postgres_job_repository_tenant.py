from __future__ import annotations

import uuid

import pytest
from psycopg_pool import ConnectionPool

from app.domain.entities.tenant import Tenant
from app.infrastructure.repositories.postgres_job_repository import (
    PostgresJobRepository,
)
from app.infrastructure.repositories.postgres_tenant_repository import (
    PostgresTenantRepository,
)
from tests.infrastructure.repositories.contract.job_repository_tenant_contract import (
    JobRepositoryTenantContract,
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


class TestPostgresJobRepositoryTenant(JobRepositoryTenantContract):
    @pytest.fixture
    def repository(self, pool):
        with pool.connection() as conn:
            conn.execute("TRUNCATE jobs, nodes CASCADE")
        return PostgresJobRepository(pool)

    @pytest.fixture
    def second_tenant_id(self, pool):
        tenant = Tenant.create(f"t-{uuid.uuid4().hex[:8]}")
        PostgresTenantRepository(pool).save(tenant)

        yield tenant.id

        # Jobs first: a job still pointing at the tenant would block
        # the delete.
        with pool.connection() as conn:
            conn.execute("TRUNCATE jobs, nodes CASCADE")
            conn.execute(
                "DELETE FROM tenants WHERE id = %s",
                (str(tenant.id),),
            )
