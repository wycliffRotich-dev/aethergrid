"""ADR 0096: a job left without a lease is reclaimed, on Postgres.

Expired-lease recovery deletes the lease row in one write and saves the
job in another. A failed job save between them leaves a RUNNING job
that no lease row points at. The pass that follows lists leases and no
longer sees it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from psycopg_pool import ConnectionPool

from app.application.reconciliation.reconciliation_loop import (
    ReconciliationLoop,
)
from app.application.reconciliation.recover_expired_lease_service import (
    RecoverExpiredLeaseService,
)
from app.application.reconciliation.recover_leaseless_job_service import (
    RecoverLeaselessJobService,
)
from app.application.reconciliation.recover_offline_node_service import (
    RecoverOfflineNodeService,
)
from app.application.services.mark_dead_workers_service import (
    MarkDeadWorkersService,
)
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.node import Node
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.entities.worker import Worker
from app.domain.enums.job_status import JobStatus
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


class FailingOnceJobRepository(PostgresJobRepository):
    """
    Loses one write, the way a dropped connection or a killed process
    does after the lease row is already gone.
    """

    fail_next_save = False

    def save(self, job: Job) -> None:
        if self.fail_next_save:
            self.fail_next_save = False
            raise RuntimeError("the write was lost")

        super().save(job)


def _running_job_with_an_expired_lease(
    pool: ConnectionPool,
) -> tuple[Node, Worker, Job]:
    node = make_node(tenant_id=DEFAULT_TENANT_ID)
    job = make_job(max_retries=3)
    job.queue()
    job.assign_to(node.id)
    node.allocate(job.resources)
    PostgresNodeRepository(pool).save(node)
    PostgresJobRepository(pool).save(job)

    worker = make_worker(node=node)
    worker.ready()
    worker.accept(job)
    worker.start()
    PostgresJobRepository(pool).save(job)
    PostgresWorkerRepository(pool).save(worker)

    PostgresLeaseRepository(pool).save(
        Lease.create(
            worker_id=worker.id,
            job_id=job.id,
            tenant_id=worker.tenant_id,
            duration=timedelta(seconds=-1),
        )
    )
    return node, worker, job


def _loop(pool: ConnectionPool, jobs: PostgresJobRepository) -> ReconciliationLoop:
    leases = PostgresLeaseRepository(pool)
    workers = PostgresWorkerRepository(pool)
    nodes = PostgresNodeRepository(pool)
    return ReconciliationLoop(
        mark_dead_workers_service=MarkDeadWorkersService(
            worker_repository=workers,
        ),
        recover_expired_lease_service=RecoverExpiredLeaseService(
            worker_repository=workers,
            job_repository=jobs,
            lease_repository=leases,
            node_repository=nodes,
        ),
        recover_offline_node_service=RecoverOfflineNodeService(
            node_repository=nodes,
            worker_repository=workers,
            job_repository=jobs,
            lease_repository=leases,
        ),
        recover_leaseless_job_service=RecoverLeaselessJobService(
            job_repository=jobs,
            lease_repository=leases,
            worker_repository=workers,
            node_repository=nodes,
        ),
    )


def test_a_job_stranded_by_a_failed_save_is_requeued_and_its_node_freed(
    pool: ConnectionPool,
) -> None:
    node, worker, job = _running_job_with_an_expired_lease(pool)
    jobs = FailingOnceJobRepository(pool)
    leases = PostgresLeaseRepository(pool)
    nodes = PostgresNodeRepository(pool)
    loop = _loop(pool, jobs)

    jobs.fail_next_save = True
    loop.execute()

    stranded = jobs.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert stranded is not None
    assert stranded.status is JobStatus.RUNNING
    assert leases.list_across_tenants() == []

    loop.execute()
    loop.execute()

    recovered = jobs.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert recovered is not None
    assert recovered.status is JobStatus.QUEUED
    assert recovered.retry_count == 1
    assert recovered.assigned_node_id is None

    stored_node = nodes.get_by_id(node.id, DEFAULT_TENANT_ID)
    assert stored_node is not None
    assert stored_node.available == stored_node.capacity

    stored_worker = PostgresWorkerRepository(pool).get_by_id(
        worker.id, worker.tenant_id
    )
    assert stored_worker is not None
    assert stored_worker.is_idle()


def test_a_running_job_with_a_live_lease_is_left_alone(
    pool: ConnectionPool,
) -> None:
    _, worker, job = _running_job_with_an_expired_lease(pool)
    leases = PostgresLeaseRepository(pool)
    leases.delete(job.id, job.tenant_id)
    leases.save(
        Lease.create(
            worker_id=worker.id,
            job_id=job.id,
            tenant_id=worker.tenant_id,
        )
    )
    jobs = PostgresJobRepository(pool)
    loop = _loop(pool, jobs)

    for _ in range(4):
        loop.execute()

    stored = jobs.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert stored is not None
    assert stored.status is JobStatus.RUNNING
