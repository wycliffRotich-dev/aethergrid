from __future__ import annotations

import os

from app.application.services.job_execution_support import (
    reclaim_job,
)
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.node import Node
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from app.infrastructure.repositories.in_memory_lease_repository import (
    InMemoryLeaseRepository,
)
from app.infrastructure.repositories.sqlite_connection import (
    create_connection,
)
from app.infrastructure.repositories.sqlite_node_repository import (
    SqliteNodeRepository,
)


def _make_node_and_job(
    job_resources: ResourceRequirements,
    max_retries: int = 1,
) -> tuple[Node, Job]:
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )
    node.allocate(job_resources)

    job = Job(
        id=JobId.new(),
        resources=job_resources,
        max_retries=max_retries,
    )
    job.queue()
    job.assign_to(node.id)
    job.start()

    return node, job


def test_reclaim_job_deletes_lease_releases_node_and_reclaims_job(
    tmp_path,
) -> None:
    """
    The full happy path: lease deleted, node's resources
    released and persisted (verified via a fresh SQLite
    connection, not the same in-memory object), job reclaimed
    back to QUEUED with a retry consumed.
    """
    job_resources = ResourceRequirements(
        cpu_cores=1,
        memory_mib=512,
        vram_mib=0,
    )
    node, job = _make_node_and_job(job_resources)

    db_path = os.path.join(tmp_path, "test.db")

    write_connection = create_connection(db_path)
    SqliteNodeRepository(write_connection).save(node)
    write_connection.close()

    job_repository = InMemoryJobRepository([job])
    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(
        Lease.create(
            worker_id=NodeId.new().value,  # placeholder, unused by delete()
            job_id=job.id,
        )
    )

    exec_connection = create_connection(db_path)
    node_repository = SqliteNodeRepository(exec_connection)

    result = reclaim_job(
        job,
        node,
        lease_repository=lease_repository,
        node_repository=node_repository,
        job_repository=job_repository,
    )
    exec_connection.close()

    assert result is True
    assert job.is_queued()
    assert job.retry_count == 1
    assert lease_repository.get_by_job_id(job.id) is None

    read_connection = create_connection(db_path)
    reloaded = SqliteNodeRepository(read_connection).get_by_id(node.id)
    read_connection.close()

    assert reloaded is not None
    assert reloaded.available.cpu_cores == 8
    assert reloaded.available.memory_mib == 16384


def test_reclaim_job_with_no_node_still_deletes_lease_and_reclaims_job() -> (
    None
):
    """
    node=None skips resource release entirely but still
    deletes the lease and reclaims the job. Covers callers
    that have already determined there is nothing to release,
    or no node at all.
    """
    job_resources = ResourceRequirements(
        cpu_cores=1,
        memory_mib=512,
        vram_mib=0,
    )
    job = Job(
        id=JobId.new(),
        resources=job_resources,
        max_retries=1,
    )
    job.queue()
    job.assign_to(NodeId.new())
    job.start()

    job_repository = InMemoryJobRepository([job])
    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(
        Lease.create(
            worker_id=NodeId.new().value,
            job_id=job.id,
        )
    )

    result = reclaim_job(
        job,
        None,
        lease_repository=lease_repository,
        node_repository=None,  # type: ignore[arg-type]
        job_repository=job_repository,
    )

    assert result is True
    assert job.is_queued()
    assert lease_repository.get_by_job_id(job.id) is None


def test_reclaim_job_returns_false_when_job_not_reclaimable() -> None:
    """
    A job already in a terminal state (e.g. it left SCHEDULED
    via the scheduler's own unschedule() path before this
    lease's TTL ran out) cannot be reclaimed. The lease is
    still deleted, since it is stale regardless, but the
    function returns False so the caller knows there is
    nothing further to persist for this job.
    """
    job_resources = ResourceRequirements(
        cpu_cores=1,
        memory_mib=512,
        vram_mib=0,
    )
    job = Job(
        id=JobId.new(),
        resources=job_resources,
        max_retries=1,
    )
    job.queue()
    job.assign_to(NodeId.new())
    job.start()
    job.complete()

    job_repository = InMemoryJobRepository([job])
    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(
        Lease.create(
            worker_id=NodeId.new().value,
            job_id=job.id,
        )
    )

    result = reclaim_job(
        job,
        None,
        lease_repository=lease_repository,
        node_repository=None,  # type: ignore[arg-type]
        job_repository=job_repository,
    )

    assert result is False
    assert lease_repository.get_by_job_id(job.id) is None
    assert job.status.name == "COMPLETED"


def test_reclaim_job_fails_outright_once_retries_exhausted() -> None:
    """
    A job with no retry budget remaining is failed outright by
    Job.reclaim() itself, and reclaim_job still returns True,
    since the job WAS successfully reclaimed, just to FAILED
    instead of QUEUED. This mirrors Job.reclaim()'s own
    documented behavior.
    """
    job_resources = ResourceRequirements(
        cpu_cores=1,
        memory_mib=512,
        vram_mib=0,
    )
    job = Job(
        id=JobId.new(),
        resources=job_resources,
        max_retries=0,
    )
    job.queue()
    job.assign_to(NodeId.new())
    job.start()

    job_repository = InMemoryJobRepository([job])
    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(
        Lease.create(
            worker_id=NodeId.new().value,
            job_id=job.id,
        )
    )

    result = reclaim_job(
        job,
        None,
        lease_repository=lease_repository,
        node_repository=None,  # type: ignore[arg-type]
        job_repository=job_repository,
    )

    assert result is True
    assert job.is_failed()
