"""ADR 0075, slice 1: assigning a job to a worker with no stored tenant.

Between migrations 0004 and 0005 an older image can register a worker
without a tenant. The composite key from a lease to its worker cannot
match such a row, so the lease is refused and the job is retried on the
next tick, until this image saves the worker once, which a heartbeat
does. Nothing is persisted by the refused attempt.
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
from app.domain.exceptions.no_available_node_error import (
    NoAvailableNodeError,
)
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


def _forget_the_tenant(pool: ConnectionPool, worker: Worker) -> None:
    """What an older image leaves behind: a worker row with no tenant."""
    with pool.connection() as conn:
        conn.execute(
            "UPDATE workers SET tenant_id = NULL WHERE id = %s",
            (str(worker.id),),
        )


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
    lease = PostgresLeaseRepository(pool).get_by_job_id(job.id)
    assert lease is not None
    assert lease.tenant_id == tenant


def test_a_worker_with_no_tenant_is_refused_until_it_is_saved_once(
    pool: ConnectionPool,
) -> None:
    tenant = _tenant(pool)
    worker, job = _idle_worker_and_assigned_job(pool, tenant)
    _forget_the_tenant(pool, worker)
    workers = PostgresWorkerRepository(pool)
    leases = PostgresLeaseRepository(pool)

    with pytest.raises(NoAvailableNodeError):
        _service(pool).execute(job)

    refused = workers.get_by_id(worker.id)
    assert refused is not None
    assert refused.is_idle()
    assert refused.running_job is None
    assert leases.get_by_job_id(job.id) is None

    workers.save(refused)  # what a heartbeat does

    assert _service(pool).execute(job).id == worker.id
    assert leases.get_by_job_id(job.id) is not None
