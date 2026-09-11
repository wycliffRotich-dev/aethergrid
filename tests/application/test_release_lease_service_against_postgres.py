from __future__ import annotations

import os

import pytest
from psycopg_pool import ConnectionPool

from app.application.services.release_lease_service import (
    ReleaseLeaseService,
)
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.exceptions.lease_not_found_error import (
    LeaseNotFoundError,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
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

TEST_DATABASE_URL = os.environ.get(
    "NEUROMESH_TEST_DATABASE_URL",
    "postgresql://neuromesh:neuromesh@localhost:5432/neuromesh_test",
)


@pytest.fixture(scope="session")
def pool():
    test_pool = ConnectionPool(
        TEST_DATABASE_URL,
        min_size=1,
        max_size=5,
        open=True,
        kwargs={"autocommit": True},
    )
    yield test_pool
    test_pool.close()


def test_release_by_stale_lease_id_is_rejected_and_reassigned_lease_survives(
    pool,
) -> None:
    """
    ADR 0037: proves ADR 0034's lease-fencing logic against a
    real, reconstructing-on-read repository, not just
    InMemoryLeaseRepository, whose shared object references
    already masked an unrelated bug once in this codebase
    (ADR 0033). Every repository instance below is
    independently constructed against the same pool, the same
    discipline already used for the SQLite job-repository
    repro that proved ADR 0033.

    Simulates the exact sequence ADR 0034 names: a lease is
    acquired, reconciliation reclaims it, the same worker is
    legitimately reassigned a different job with a new lease,
    and a stale caller still holding the original lease's
    identity attempts to release it. That attempt must be
    rejected, and the second, legitimately-held lease must
    survive untouched.
    """
    with pool.connection() as conn:
        conn.execute("TRUNCATE leases, workers, jobs, nodes CASCADE")

    node_repository = PostgresNodeRepository(pool)
    worker_repository = PostgresWorkerRepository(pool)
    job_repository = PostgresJobRepository(pool)

    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=8192,
        ),
    )
    node_repository.save(node)

    worker = Worker(
        id=WorkerId.new(),
        node=node,
    )
    worker_repository.save(worker)

    job_one = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
    )
    job_repository.save(job_one)

    job_two = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
    )
    job_repository.save(job_two)

    # Step 1: acquire the original lease, via its own repository
    # instance, matching the "each actor gets its own reader/
    # writer" idiom already proven in the SQLite repro.
    acquiring_repository = PostgresLeaseRepository(pool)
    original_lease = Lease.create(
        worker_id=worker.id,
        job_id=job_one.id,
    )
    acquiring_repository.save(original_lease)

    # Step 2: reconciliation reclaims it, independently.
    reclaiming_repository = PostgresLeaseRepository(pool)
    reclaiming_repository.delete(job_one.id)

    # Step 3: the same worker is legitimately reassigned a
    # different job, with its own new lease.
    reassigning_repository = PostgresLeaseRepository(pool)
    replacement_lease = Lease.create(
        worker_id=worker.id,
        job_id=job_two.id,
    )
    reassigning_repository.save(replacement_lease)

    # Step 4: the stale caller, still holding the *original*
    # lease's identity, attempts to release it, via its own,
    # independent repository instance.
    releasing_repository = PostgresLeaseRepository(pool)
    releasing_worker_repository = PostgresWorkerRepository(pool)
    service = ReleaseLeaseService(
        lease_repository=releasing_repository,
        worker_repository=releasing_worker_repository,
    )

    with pytest.raises(LeaseNotFoundError):
        service.execute(worker.id, original_lease.id)

    # Step 5: verify, via a fourth, independent repository
    # instance, that the replacement lease survived untouched.
    verifying_repository = PostgresLeaseRepository(pool)
    surviving_lease = verifying_repository.get_by_worker_id(worker.id)

    assert surviving_lease is not None
    assert surviving_lease.id == replacement_lease.id
    assert surviving_lease.job_id == job_two.id
