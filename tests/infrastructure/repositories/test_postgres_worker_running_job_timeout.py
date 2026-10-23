from __future__ import annotations

from datetime import timedelta

import pytest
from psycopg_pool import ConnectionPool

from app.domain.entities.job import DEFAULT_EXECUTION_TIMEOUT
from app.domain.enums.worker_status import WorkerStatus
from app.infrastructure.repositories.postgres_job_repository import (
    PostgresJobRepository,
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


@pytest.fixture()
def repositories(pool):
    with pool.connection() as conn:
        conn.execute("TRUNCATE workers, jobs, nodes CASCADE")

    return (
        PostgresNodeRepository(pool),
        PostgresJobRepository(pool),
        PostgresWorkerRepository(pool),
    )


def _save_busy_worker(repositories, job):
    node_repository, job_repository, worker_repository = repositories

    node = make_node()
    node_repository.save(node)
    job_repository.save(job)

    worker = make_worker(
        node=node,
        status=WorkerStatus.BUSY,
        running_job=job,
    )
    worker_repository.save(worker)

    return worker, worker_repository


def test_running_job_keeps_its_execution_timeout(repositories) -> None:
    """
    The agent takes a job's timeout from worker.running_job, and that
    job is rebuilt by the worker repository's own mapper, separate from
    the job repository's. A timeout that survives a job round trip but
    is lost here would still run every command with the default.
    """
    job = make_job(execution_timeout=timedelta(seconds=45))
    worker, worker_repository = _save_busy_worker(repositories, job)

    reloaded = worker_repository.get_by_id(worker.id, worker.tenant_id)

    assert reloaded is not None
    assert reloaded.running_job is not None
    assert reloaded.running_job.execution_timeout == timedelta(seconds=45)


def test_running_job_with_null_timeout_loads_the_default(
    pool,
    repositories,
) -> None:
    job = make_job(execution_timeout=timedelta(seconds=45))
    worker, worker_repository = _save_busy_worker(repositories, job)

    with pool.connection() as conn:
        conn.execute(
            "UPDATE jobs SET execution_timeout_seconds = NULL WHERE id = %s",
            (str(job.id),),
        )

    reloaded = worker_repository.get_by_id(worker.id, worker.tenant_id)

    assert reloaded is not None
    assert reloaded.running_job is not None
    assert reloaded.running_job.execution_timeout == DEFAULT_EXECUTION_TIMEOUT
