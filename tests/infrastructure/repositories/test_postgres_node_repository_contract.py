from __future__ import annotations

import pytest
from psycopg_pool import ConnectionPool

from app.infrastructure.repositories.postgres_node_repository import (
    PostgresNodeRepository,
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
