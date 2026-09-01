from app.application.services.create_worker_service import (
    CreateWorkerService,
)
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.enums.worker_status import WorkerStatus
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)


def test_create_worker_service_creates_and_persists_worker() -> None:
    repository = InMemoryWorkerRepository()

    service = CreateWorkerService(
        worker_repository=repository,
    )

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
    service = CreateWorkerService(
        worker_repository=repository,
    )
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
    and returns the worker to IDLE, the same as reconciliation's
    existing Worker.recover() behavior (ADR 0030).
    """
    repository = InMemoryWorkerRepository()
    service = CreateWorkerService(
        worker_repository=repository,
    )
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
