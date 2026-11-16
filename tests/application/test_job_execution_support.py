from __future__ import annotations

import os

from app.application.services.job_execution_support import (
    reclaim_job,
    reclaim_leaseless_job,
)
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.node import Node
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.enums.job_status import JobStatus
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
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)
from app.infrastructure.repositories.sqlite_connection import (
    create_connection,
)
from app.infrastructure.repositories.sqlite_node_repository import (
    SqliteNodeRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node


def _make_node_and_job(
    job_resources: ResourceRequirements,
    max_retries: int = 1,
) -> tuple[Node, Job]:
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )
    node.allocate(job_resources)

    job = make_job(
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
            tenant_id=DEFAULT_TENANT_ID,
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
    assert lease_repository.get_by_job_id(job.id, job.tenant_id) is None

    read_connection = create_connection(db_path)
    reloaded = SqliteNodeRepository(read_connection).get_by_id(node.id, DEFAULT_TENANT_ID)
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
    job = make_job(
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
            tenant_id=DEFAULT_TENANT_ID,
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
    assert lease_repository.get_by_job_id(job.id, job.tenant_id) is None


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
    job = make_job(
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
            tenant_id=DEFAULT_TENANT_ID,
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
    assert lease_repository.get_by_job_id(job.id, job.tenant_id) is None
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
    job = make_job(
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
            tenant_id=DEFAULT_TENANT_ID,
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


def test_reclaim_job_does_not_credit_node_when_job_not_reclaimable(
    tmp_path,
) -> None:
    """
    A job that can no longer be reclaimed must not give its
    resources back to the node. The node also hosts another
    job, so a credit for a job that already finished would make
    the node report capacity it does not have. The persisted
    node is read back through a fresh connection, not the same
    object.
    """
    job_resources = ResourceRequirements(
        cpu_cores=1,
        memory_mib=512,
        vram_mib=0,
    )
    node, job = _make_node_and_job(job_resources)
    node.allocate(
        ResourceRequirements(
            cpu_cores=2,
            memory_mib=1024,
            vram_mib=0,
        )
    )
    job.complete()

    db_path = os.path.join(tmp_path, "test.db")

    write_connection = create_connection(db_path)
    SqliteNodeRepository(write_connection).save(node)
    write_connection.close()

    job_repository = InMemoryJobRepository([job])
    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(
        Lease.create(
            worker_id=NodeId.new().value,
            job_id=job.id,
            tenant_id=DEFAULT_TENANT_ID,
        )
    )

    exec_connection = create_connection(db_path)
    result = reclaim_job(
        job,
        node,
        lease_repository=lease_repository,
        node_repository=SqliteNodeRepository(exec_connection),
        job_repository=job_repository,
    )
    exec_connection.close()

    assert result is False
    assert job.status.name == "COMPLETED"

    read_connection = create_connection(db_path)
    reloaded = SqliteNodeRepository(read_connection).get_by_id(
        node.id, DEFAULT_TENANT_ID
    )
    read_connection.close()

    assert reloaded is not None
    assert reloaded.available.cpu_cores == 5
    assert reloaded.available.memory_mib == 14848


# --- reclaim_leaseless_job (ADR 0096) ---


_ONE_CORE = ResourceRequirements(cpu_cores=1, memory_mib=512, vram_mib=0)


def _leaseless_setup() -> tuple[
    Node, Job, InMemoryJobRepository, InMemoryLeaseRepository, InMemoryNodeRepository
]:
    node, job = _make_node_and_job(_ONE_CORE, max_retries=3)
    leases = InMemoryLeaseRepository()
    jobs = InMemoryJobRepository([job], lease_repository=leases)
    nodes = InMemoryNodeRepository([node])
    return node, job, jobs, leases, nodes


def test_reclaim_leaseless_job_returns_a_reclaimed_copy_and_leaves_the_job_alone() -> (
    None
):
    node, job, jobs, _, nodes = _leaseless_setup()

    reclaimed = reclaim_leaseless_job(
        job,
        node,
        node_repository=nodes,
        job_repository=jobs,
    )

    assert reclaimed is not None
    assert reclaimed is not job
    assert reclaimed.is_queued()
    assert reclaimed.retry_count == 1
    assert job.is_running()
    assert job.retry_count == 0

    stored = jobs.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert stored is not None
    assert stored.is_queued()
    assert node.available.cpu_cores == 8


def test_reclaim_leaseless_job_refused_changes_nothing() -> None:
    """
    A lease exists, so the fenced write is refused. The caller's job
    is not left looking reclaimed, and the node is not credited.
    """
    node, job, jobs, leases, nodes = _leaseless_setup()
    leases.save(
        Lease.create(
            worker_id=NodeId.new().value,
            job_id=job.id,
            tenant_id=DEFAULT_TENANT_ID,
        )
    )

    reclaimed = reclaim_leaseless_job(
        job,
        node,
        node_repository=nodes,
        job_repository=jobs,
    )

    assert reclaimed is None
    assert job.is_running()
    assert job.retry_count == 0
    assert job.assigned_node_id == node.id
    assert node.available.cpu_cores == 7


def test_reclaim_leaseless_job_is_fenced_on_the_status_of_the_job_handed_in() -> (
    None
):
    """
    The caller read the job as RUNNING. A cancellation request was
    saved after that, so the stored job is CANCELLING, and the write
    fenced on RUNNING is refused.
    """
    node, job, _, leases, nodes = _leaseless_setup()
    jobs = InMemoryJobRepository(lease_repository=leases)
    cancelling = make_job(
        id=job.id,
        resources=_ONE_CORE,
    )
    cancelling.queue()
    cancelling.assign_to(node.id)
    cancelling.start()
    cancelling.request_cancellation()
    jobs.save(cancelling)

    reclaimed = reclaim_leaseless_job(
        job,
        node,
        node_repository=nodes,
        job_repository=jobs,
    )

    assert reclaimed is None
    stored = jobs.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert stored is not None
    assert stored.status is JobStatus.CANCELLING
    assert node.available.cpu_cores == 7


def test_reclaim_leaseless_job_skips_a_job_that_cannot_be_reclaimed() -> None:
    node, job, jobs, _, nodes = _leaseless_setup()
    job.complete(exit_code=0)
    jobs.save(job)

    assert (
        reclaim_leaseless_job(
            job,
            node,
            node_repository=nodes,
            job_repository=jobs,
        )
        is None
    )
    assert node.available.cpu_cores == 7
