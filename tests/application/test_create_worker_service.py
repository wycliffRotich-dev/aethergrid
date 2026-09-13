from datetime import timedelta

from app.application.services.create_worker_service import (
    CreateWorkerService,
)
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.enums.worker_status import WorkerStatus
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
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)


def _make_service(
    worker_repository: InMemoryWorkerRepository,
    job_repository: InMemoryJobRepository | None = None,
    lease_repository: InMemoryLeaseRepository | None = None,
    node_repository: InMemoryNodeRepository | None = None,
) -> CreateWorkerService:
    return CreateWorkerService(
        worker_repository=worker_repository,
        job_repository=job_repository or InMemoryJobRepository(),
        lease_repository=lease_repository or InMemoryLeaseRepository(),
        node_repository=node_repository or InMemoryNodeRepository(),
    )


def test_create_worker_service_creates_and_persists_worker() -> None:
    repository = InMemoryWorkerRepository()

    service = _make_service(repository)

    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = service.execute(
        node=node,
    )

    assert isinstance(
        worker,
        Worker,
    )

    stored = repository.get_by_id(
        worker.id,
    )

    assert stored is worker
    assert stored.node is node


def test_create_worker_service_reclaims_existing_worker_for_node() -> None:
    """
    Re-registering against a node that already has a worker
    reclaims it, preserving the same WorkerId, rather than
    creating a duplicate (ADR 0030).
    """
    repository = InMemoryWorkerRepository()
    service = _make_service(repository)
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    first = service.execute(
        node=node,
    )
    second = service.execute(
        node=node,
    )

    assert second.id == first.id
    assert len(repository.list()) == 1


def test_create_worker_service_reclaim_recovers_abandoned_job() -> None:
    """
    Reclaiming a worker that still shows a running job (e.g. an
    agent that crashed mid-job and restarted) forgets that job
    and returns the worker to IDLE (ADR 0030).
    """
    repository = InMemoryWorkerRepository()
    service = _make_service(repository)
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = service.execute(
        node=node,
    )
    worker.status = WorkerStatus.BUSY
    repository.save(worker)

    reclaimed = service.execute(
        node=node,
    )

    assert reclaimed.id == worker.id
    assert reclaimed.is_idle()
    assert reclaimed.running_job is None


def test_create_worker_service_reclaim_releases_lease_and_node_resources() -> (
    None
):
    """
    Regression test (ADR 0039): reclaiming a worker that still
    holds a real, leased job must delete that job's lease,
    release its allocated resources back to the node, and
    reclaim the job itself, not just forget it on the worker.

    Before this was fixed, CreateWorkerService called
    Worker.recover() directly, which only cleared the worker's
    own running_job pointer. The job's lease and the node's
    allocated resources survived untouched, and the job itself
    was never transitioned via reclaim(). This left a stale
    lease and shrunk node capacity in place, and created a race
    where the now-idle worker could be assigned a new job before
    the old lease expired, corrupting the new job's tracking
    once the old lease's eventual expiry triggered
    RecoverExpiredLeaseService against the wrong job.
    """
    job_resources = ResourceRequirements(
        cpu_cores=1,
        memory_mib=512,
        vram_mib=0,
    )

    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )
    node.allocate(job_resources)

    worker_repository = InMemoryWorkerRepository()
    job_repository = InMemoryJobRepository()
    lease_repository = InMemoryLeaseRepository()
    node_repository = InMemoryNodeRepository([node])

    service = _make_service(
        worker_repository,
        job_repository=job_repository,
        lease_repository=lease_repository,
        node_repository=node_repository,
    )

    worker = service.execute(
        node=node,
    )

    job = Job(
        id=JobId.new(),
        resources=job_resources,
        max_retries=1,
    )
    job.queue()
    job.assign_to(node.id)
    job_repository.save(job)

    worker.accept(job)
    worker.start()
    worker_repository.save(worker)

    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
        duration=timedelta(seconds=30),
    )
    lease_repository.save(lease)

    reclaimed = service.execute(
        node=node,
    )

    assert reclaimed.is_idle()
    assert reclaimed.running_job is None

    assert lease_repository.get_by_job_id(job.id) is None

    recovered_node = node_repository.get_by_id(node.id)
    assert recovered_node.available.cpu_cores == 8
    assert recovered_node.available.memory_mib == 16384

    recovered_job = job_repository.get_by_id(job.id)
    assert recovered_job.is_queued()
    assert recovered_job.retry_count == 1
