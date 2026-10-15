from __future__ import annotations

from collections.abc import Iterator

import pytest
from psycopg.rows import tuple_row
from psycopg_pool import ConnectionPool

from app.domain.entities.tenant import Tenant
from app.infrastructure.repositories.postgres_tenant_repository import (
    PostgresTenantRepository,
)


@pytest.fixture
def single_connection_pool(test_database_url: str) -> Iterator[ConnectionPool]:
    """A pool of one, so the next borrower gets the connection the last used."""
    pool = ConnectionPool(
        test_database_url,
        min_size=1,
        max_size=1,
        open=True,
        kwargs={"autocommit": True},
    )
    try:
        pool.wait(timeout=10.0)
        yield pool
    finally:
        with pool.connection() as conn:
            conn.execute("DELETE FROM tenants WHERE name = 'row-factory-probe'")
        pool.close()


def _row_factory_after(pool: ConnectionPool) -> object:
    with pool.connection() as conn:
        return conn.row_factory


def test_the_tenant_repository_leaves_the_default_row_factory(
    single_connection_pool: ConnectionPool,
) -> None:
    """
    A repository must not change the row factory of the connection it
    borrows, because the pool hands that connection to the next caller.
    """
    repository = PostgresTenantRepository(single_connection_pool)
    tenant = Tenant.create("row-factory-probe")

    repository.save(tenant)
    repository.save(tenant)
    repository.get_by_id(tenant.id)
    repository.get_by_name(tenant.name)

    assert _row_factory_after(single_connection_pool) is tuple_row
