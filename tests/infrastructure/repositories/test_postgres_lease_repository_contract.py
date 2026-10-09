from __future__ import annotations

import pytest
from psycopg_pool import ConnectionPool

from app.domain.entities.lease import DEFAULT_LEASE_DURATION
from app.domain.entities.worker import Worker
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
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
from tests.infrastructure.repositories.contract.lease_repository_contract import (
    LeaseRepositoryContract,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node


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


class TestPostgresLeaseRepositoryContract(LeaseRepositoryContract):
    """
    The base LeaseRepositoryContract's _make_lease() builds
    a throwaway Node, Worker, and Job purely to derive valid
    worker_id/job_id for the returned Lease -- it never
    persists them, which is fine for the in-memory
    repository. The postgres `leases` table enforces real
    foreign keys on both worker_id and job_id, so here we
    override _make_lease() to persist matching Node, Worker,
    and Job rows using the exact same ids before returning
    the lease.
    """

    @pytest.fixture
    def repository(self, pool):
        with pool.connection() as conn:
            conn.execute(
                "TRUNCATE leases, workers, jobs, nodes CASCADE"
            )

        node_repository = PostgresNodeRepository(pool)
        worker_repository = PostgresWorkerRepository(pool)
        job_repository = PostgresJobRepository(pool)

        original_make_lease = self._make_lease

        def _make_lease_and_persist_dependencies(
            *,
            duration=DEFAULT_LEASE_DURATION,
        ):
            lease = original_make_lease(duration=duration)

            node = make_node(
                id=NodeId.new(),
                capacity=ResourceRequirements(
                    cpu_cores=8,
                    memory_mib=16384,
                    vram_mib=8192,
                ),
            )
            node_repository.save(node)

            worker = Worker(
                id=lease.worker_id,
                node=node,
            )
            worker_repository.save(worker)

            job = make_job(
                id=lease.job_id,
                resources=ResourceRequirements(
                    cpu_cores=1,
                    memory_mib=512,
                    vram_mib=0,
                ),
            )
            job_repository.save(job)

            return lease

        self._make_lease = _make_lease_and_persist_dependencies

        return PostgresLeaseRepository(pool)
