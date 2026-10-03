from __future__ import annotations

import pytest
from psycopg_pool import ConnectionPool

from app.infrastructure.repositories.postgres_api_key_repository import (
    PostgresApiKeyRepository,
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
    api_keys has no foreign key dependencies (unlike leases,
    which needs a real Node/Worker/Job to satisfy its FKs), so
    unlike TestPostgresLeaseRepositoryContract this needs no
    _make_api_key() override -- the base contract's version
    works unmodified against Postgres too.
    """

    @pytest.fixture
    def repository(self, pool):
        with pool.connection() as conn:
            conn.execute("TRUNCATE api_keys")

        return PostgresApiKeyRepository(pool)
