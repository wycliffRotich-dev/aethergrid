"""JobRepository.save_if_leaseless on Postgres (ADR 0096).

The write applies only while the job still has the status the caller
read and no lease row exists, as one transaction on a locked row.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from psycopg_pool import ConnectionPool

from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.enums.job_status import JobStatus
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


def _running_job_with_a_worker(pool: ConnectionPool):  # type: ignore[no-untyped-def]
    node = make_node(tenant_id=DEFAULT_TENANT_ID)
    PostgresNodeRepository(pool).save(node)

    job = make_job(max_retries=3)
    job.queue()
    job.assign_to(node.id)
    PostgresJobRepository(pool).save(job)

    worker = make_worker(node=node)
    worker.ready()
    worker.accept(job)
    worker.start()
    PostgresJobRepository(pool).save(job)
    PostgresWorkerRepository(pool).save(worker)

    return job, worker


def _reclaimed(job: Job) -> Job:
    job.reclaim()
    return job


def test_it_saves_a_job_that_kept_its_status_and_has_no_lease(
    pool: ConnectionPool,
) -> None:
    repository = PostgresJobRepository(pool)
    job, _ = _running_job_with_a_worker(pool)

    assert repository.save_if_leaseless(_reclaimed(job), frozenset({JobStatus.RUNNING}))

    stored = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert stored is not None
    assert stored.status is JobStatus.QUEUED
    assert stored.retry_count == 1


def test_it_refuses_a_job_whose_status_changed(pool: ConnectionPool) -> None:
    repository = PostgresJobRepository(pool)
    job, _ = _running_job_with_a_worker(pool)

    finished = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert finished is not None
    finished.complete(exit_code=0)
    repository.save(finished)

    assert not repository.save_if_leaseless(
        _reclaimed(job), frozenset({JobStatus.RUNNING})
    )

    stored = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert stored is not None
    assert stored.status is JobStatus.COMPLETED


def test_it_refuses_a_job_that_has_a_lease(pool: ConnectionPool) -> None:
    repository = PostgresJobRepository(pool)
    job, worker = _running_job_with_a_worker(pool)
    PostgresLeaseRepository(pool).save(
        Lease.create(
            worker_id=worker.id,
            job_id=job.id,
            tenant_id=worker.tenant_id,
        )
    )

    assert not repository.save_if_leaseless(
        _reclaimed(job), frozenset({JobStatus.RUNNING})
    )

    stored = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert stored is not None
    assert stored.status is JobStatus.RUNNING


def test_it_refuses_a_job_that_does_not_exist(pool: ConnectionPool) -> None:
    repository = PostgresJobRepository(pool)
    job = make_job()
    job.queue()
    job.assign_to(make_node().id)

    assert not repository.save_if_leaseless(job, frozenset({JobStatus.SCHEDULED}))


def test_it_does_not_reach_a_job_in_another_tenant(
    pool: ConnectionPool,
) -> None:
    repository = PostgresJobRepository(pool)
    job, _ = _running_job_with_a_worker(pool)

    other_tenant = TenantId.new()
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO tenants (id, name, created_at) "
            "VALUES (%s, %s, now())",
            (str(other_tenant.value), f"t-{uuid.uuid4().hex[:12]}"),
        )

    as_other_tenant = make_job(id=job.id, tenant_id=other_tenant)
    as_other_tenant.queue()

    assert not repository.save_if_leaseless(
        as_other_tenant, frozenset({JobStatus.RUNNING})
    )

    stored = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert stored is not None
    assert stored.status is JobStatus.RUNNING


def test_it_waits_for_a_lease_insert_in_flight_and_then_refuses(
    pool: ConnectionPool,
) -> None:
    """
    A lease inserted by another connection that has not committed yet.
    The insert holds a lock on the job row through its foreign key, so
    the fenced write waits for it, and when the insert commits the
    write finds the lease and refuses. Without the row lock the write
    would have gone ahead and left a live lease pointing at a QUEUED
    job.
    """
    repository = PostgresJobRepository(pool)
    job, worker = _running_job_with_a_worker(pool)
    result: list[bool] = []

    def attempt() -> None:
        result.append(
            repository.save_if_leaseless(
                _reclaimed(job), frozenset({JobStatus.RUNNING})
            )
        )

    writer = threading.Thread(target=attempt)

    with pool.connection() as conn, conn.transaction():
        now = datetime.now(UTC)
        conn.execute(
            "INSERT INTO leases (id, worker_id, job_id, tenant_id, "
            "acquired_at, expires_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                str(uuid.uuid4()),
                str(worker.id),
                str(job.id),
                str(worker.tenant_id.value),
                now,
                now + timedelta(hours=1),
            ),
        )

        writer.start()
        time.sleep(0.5)

        assert writer.is_alive(), "the write did not wait for the insert"

    writer.join(timeout=10)

    assert not writer.is_alive()
    assert result == [False]

    stored = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert stored is not None
    assert stored.status is JobStatus.RUNNING
