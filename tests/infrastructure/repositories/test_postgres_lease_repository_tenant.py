"""ADR 0075, slice 1: the Postgres lease repository and the tenant."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg.rows import tuple_row
from psycopg_pool import ConnectionPool

from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.worker import Worker
from app.domain.exceptions.worker_not_found_error import WorkerNotFoundError
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.postgres_job_repository import (
    PostgresJobRepository,
)
from app.infrastructure.repositories.postgres_lease_repository import (
    PostgresLeaseRepository,
)
from app.infrastructure.repositories.postgres_node_repository import (
    PostgresNodeRepository,
)
from app.infrastructure.repositories.postgres_worker_repository import (
    PostgresWorkerRepository,
)
from tests.support.jobs import make_job
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


def _persist_worker(pool: ConnectionPool, tenant_id: TenantId) -> Worker:
    node = make_node(tenant_id=tenant_id)
    PostgresNodeRepository(pool).save(node)
    worker = make_worker(node=node)
    PostgresWorkerRepository(pool).save(worker)
    return worker


def _persist_job(pool: ConnectionPool, tenant_id: TenantId) -> Job:
    job = make_job(tenant_id=tenant_id)
    PostgresJobRepository(pool).save(job)
    return job


def _stored_lease_tenant(pool: ConnectionPool, lease_id: uuid.UUID) -> str | None:
    with pool.connection() as conn:
        row = (
            conn.cursor(row_factory=tuple_row)
            .execute(
                "SELECT tenant_id::text FROM leases WHERE id = %s",
                (str(lease_id),),
            )
            .fetchone()
        )
    assert row is not None
    return row[0]


def test_saving_a_lease_writes_its_tenant(pool: ConnectionPool) -> None:
    tenant = _tenant(pool)
    worker = _persist_worker(pool, tenant)
    job = _persist_job(pool, tenant)
    lease = Lease.create(worker_id=worker.id, job_id=job.id, tenant_id=tenant)

    PostgresLeaseRepository(pool).save(lease)

    assert _stored_lease_tenant(pool, lease.id) == str(tenant.value)
    fetched = PostgresLeaseRepository(pool).get_by_job_id(job.id, tenant)
    assert fetched is not None
    assert fetched.tenant_id == tenant


def test_a_lease_for_a_missing_worker_raises_worker_not_found(
    pool: ConnectionPool,
) -> None:
    tenant = _tenant(pool)
    job = _persist_job(pool, tenant)
    lease = Lease.create(
        worker_id=WorkerId.new(), job_id=job.id, tenant_id=tenant
    )

    with pytest.raises(WorkerNotFoundError):
        PostgresLeaseRepository(pool).save(lease)


def test_a_lease_in_another_tenant_than_its_worker_raises_worker_not_found(
    pool: ConnectionPool,
) -> None:
    tenant_a = _tenant(pool)
    tenant_b = _tenant(pool)
    worker = _persist_worker(pool, tenant_a)
    job = _persist_job(pool, tenant_b)
    lease = Lease.create(worker_id=worker.id, job_id=job.id, tenant_id=tenant_b)

    with pytest.raises(WorkerNotFoundError):
        PostgresLeaseRepository(pool).save(lease)


def test_a_lease_whose_job_is_in_another_tenant_is_refused(
    pool: ConnectionPool,
) -> None:
    tenant_a = _tenant(pool)
    tenant_b = _tenant(pool)
    worker = _persist_worker(pool, tenant_a)
    job = _persist_job(pool, tenant_b)
    lease = Lease.create(worker_id=worker.id, job_id=job.id, tenant_id=tenant_a)

    with pytest.raises(psycopg.errors.ForeignKeyViolation) as refused:
        PostgresLeaseRepository(pool).save(lease)

    assert refused.value.diag.constraint_name == "leases_job_same_tenant"
