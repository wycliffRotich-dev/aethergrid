"""ADR 0075: assigning a job to a worker whose tenant is stored.

After migration 0005 every worker row has a tenant, so the assignment
reaches the lease and the lease carries the tenant of its worker.
"""

from __future__ import annotations

import uuid

import pytest
from psycopg_pool import ConnectionPool

from app.application.services.acquire_lease_service import (
    AcquireLeaseService,
)
from app.application.services.assign_worker_service import (
    AssignWorkerService,
)
from app.domain.entities.job import Job
from app.domain.entities.worker import Worker
from app.domain.value_objects.tenant_id import TenantId
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


def _idle_worker_and_assigned_job(
    pool: ConnectionPool, tenant_id: TenantId
) -> tuple[Worker, Job]:
    node = make_node(tenant_id=tenant_id)
    PostgresNodeRepository(pool).save(node)
    job = make_job(tenant_id=tenant_id)
    job.queue()
    job.assign_to(node.id)
    PostgresJobRepository(pool).save(job)
    worker = make_worker(node=node)
    worker.ready()
    PostgresWorkerRepository(pool).save(worker)
    return worker, job


def _service(pool: ConnectionPool) -> AssignWorkerService:
    return AssignWorkerService(
        worker_repository=PostgresWorkerRepository(pool),
        acquire_lease_service=AcquireLeaseService(
            lease_repository=PostgresLeaseRepository(pool),
        ),
    )


def test_a_worker_with_a_tenant_is_assigned_the_job(
    pool: ConnectionPool,
) -> None:
    tenant = _tenant(pool)
    worker, job = _idle_worker_and_assigned_job(pool, tenant)

    assigned = _service(pool).execute(job)

    assert assigned.id == worker.id
    lease = PostgresLeaseRepository(pool).get_by_job_id(job.id, job.tenant_id)
    assert lease is not None
    assert lease.tenant_id == tenant
