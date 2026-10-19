"""ADR 0075, slice 1: the Postgres worker repository writes the tenant."""

from __future__ import annotations

import uuid

import pytest
from psycopg.rows import tuple_row
from psycopg_pool import ConnectionPool

from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.postgres_node_repository import (
    PostgresNodeRepository,
)
from app.infrastructure.repositories.postgres_worker_repository import (
    PostgresWorkerRepository,
)
from tests.support.nodes import make_node
from tests.support.workers import make_worker


@pytest.fixture
def pool(test_database_url: str):
    test_pool = ConnectionPool(
        test_database_url,
        min_size=1,
        max_size=5,
        open=True,
        kwargs={"autocommit": True},
    )
    with test_pool.connection() as conn:
        conn.execute("TRUNCATE leases, workers, jobs, nodes CASCADE")
    yield test_pool
    test_pool.close()


def _tenant(pool: ConnectionPool) -> TenantId:
    tenant_id = TenantId.new()
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO tenants (id, name, created_at) VALUES (%s, %s, now())",
            (str(tenant_id.value), f"t-{uuid.uuid4().hex[:12]}"),
        )
    return tenant_id


def _stored_tenant(pool: ConnectionPool, worker_id: WorkerId) -> str | None:
    with pool.connection() as conn:
        row = (
            conn.cursor(row_factory=tuple_row)
            .execute(
                "SELECT tenant_id::text FROM workers WHERE id = %s",
                (str(worker_id),),
            )
            .fetchone()
        )
    assert row is not None
    return row[0]


def test_saving_a_worker_writes_the_tenant_of_its_node(
    pool: ConnectionPool,
) -> None:
    tenant = _tenant(pool)
    node = make_node(tenant_id=tenant)
    PostgresNodeRepository(pool).save(node)
    worker = make_worker(node=node)

    PostgresWorkerRepository(pool).save(worker)

    assert _stored_tenant(pool, worker.id) == str(tenant.value)


def test_saving_a_worker_an_older_image_wrote_repairs_its_tenant(
    pool: ConnectionPool,
) -> None:
    tenant = _tenant(pool)
    node = make_node(tenant_id=tenant)
    PostgresNodeRepository(pool).save(node)
    worker = make_worker(node=node)
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO workers (id, node_id, status, last_seen_at) "
            "VALUES (%s, %s, 'IDLE', now())",
            (str(worker.id), str(node.id)),
        )
    assert _stored_tenant(pool, worker.id) is None

    PostgresWorkerRepository(pool).save(worker)

    assert _stored_tenant(pool, worker.id) == str(tenant.value)
