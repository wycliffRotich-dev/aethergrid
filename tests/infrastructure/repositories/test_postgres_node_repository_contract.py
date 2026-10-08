from __future__ import annotations

import uuid

import pytest
from psycopg_pool import ConnectionPool

from app.domain.entities.tenant import Tenant
from app.infrastructure.repositories.postgres_node_repository import (
    PostgresNodeRepository,
)
from app.infrastructure.repositories.postgres_tenant_repository import (
    PostgresTenantRepository,
)
from tests.infrastructure.repositories.contract.node_repository_contract import (
    NodeRepositoryContract,
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


class TestPostgresNodeRepositoryContract(NodeRepositoryContract):
    @pytest.fixture
    def repository(self, pool):
        with pool.connection() as conn:
            conn.execute("TRUNCATE nodes CASCADE")
        return PostgresNodeRepository(pool)

    @pytest.fixture
    def second_tenant_id(self, pool):
        tenant = Tenant.create(f"t-{uuid.uuid4().hex[:8]}")
        PostgresTenantRepository(pool).save(tenant)

        yield tenant.id

        # Nodes first: a node still pointing at the tenant would
        # block the delete.
        with pool.connection() as conn:
            conn.execute("TRUNCATE nodes CASCADE")
            conn.execute(
                "DELETE FROM tenants WHERE id = %s",
                (str(tenant.id),),
            )
