"""ADR 0075, slice 1: a refused assignment records no event.

A worker with no stored tenant makes the lease insert fail, and the
scheduler retries the job on its next tick. Each pass must leave no
WorkerAssigned event, because no assignment happened.
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
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.job import Job
from app.domain.entities.worker import Worker
from app.domain.exceptions.no_available_node_error import (
    NoAvailableNodeError,
)
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.postgres_event_repository import (
    PostgresEventRepository,
)
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


def _service(
    pool: ConnectionPool, events: PostgresEventRepository
) -> AssignWorkerService:
    """Wired with the event service, as app/presentation/dependencies.py does."""
    recorder = RecordJobEventsService(event_repository=events)
    return AssignWorkerService(
        worker_repository=PostgresWorkerRepository(pool),
        acquire_lease_service=AcquireLeaseService(
            lease_repository=PostgresLeaseRepository(pool),
            record_job_events_service=recorder,
        ),
        record_job_events_service=recorder,
    )


def test_a_refused_assignment_records_no_event(
    pool: ConnectionPool,
) -> None:
    tenant = _tenant(pool)
    worker, job = _idle_worker_and_assigned_job(pool, tenant)
    _forget_the_tenant(pool, worker)
    events = PostgresEventRepository(pool)
    service = _service(pool, events)

    for _ in range(3):
        with pytest.raises(NoAvailableNodeError):
            service.execute(job)

    assert [e.event_type for e in events.list(tenant)] == []


def test_an_assignment_records_the_assignment_and_the_lease(
    pool: ConnectionPool,
) -> None:
    tenant = _tenant(pool)
    _, job = _idle_worker_and_assigned_job(pool, tenant)
    events = PostgresEventRepository(pool)

    _service(pool, events).execute(job)

    assert sorted(e.event_type for e in events.list(tenant)) == [
        "LeaseAcquired",
        "WorkerAssigned",
    ]
