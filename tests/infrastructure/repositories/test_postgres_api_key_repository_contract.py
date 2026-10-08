from __future__ import annotations

import uuid

import pytest
from psycopg_pool import ConnectionPool

from app.domain.entities.tenant import Tenant
from app.infrastructure.repositories.postgres_api_key_repository import (
    PostgresApiKeyRepository,
)
from app.infrastructure.repositories.postgres_tenant_repository import (
    PostgresTenantRepository,
)
from tests.infrastructure.repositories.contract.api_key_repository_contract import (
    ApiKeyRepositoryContract,
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


class TestPostgresApiKeyRepositoryContract(
    ApiKeyRepositoryContract,
):
    """
    api_keys depends on tenants: every key needs a real tenant
    row, and an issuer must share its child's tenant. The
    default tenant already exists after the schema upgrade, so
    the base contract's _make_api_key() works unmodified.
    Tests that need a second tenant get a real tenant row from
    the second_tenant_id fixture below.
    """

    @pytest.fixture
    def repository(self, pool):
        with pool.connection() as conn:
            conn.execute("TRUNCATE api_keys")

        return PostgresApiKeyRepository(pool)

    @pytest.fixture
    def second_tenant_id(self, pool):
        tenant = Tenant.create(f"t-{uuid.uuid4().hex[:8]}")
        PostgresTenantRepository(pool).save(tenant)

        yield tenant.id

        # Keys first: a key still pointing at the tenant would
        # block the delete.
        with pool.connection() as conn:
            conn.execute("TRUNCATE api_keys")
            conn.execute(
                "DELETE FROM tenants WHERE id = %s",
                (str(tenant.id),),
            )
