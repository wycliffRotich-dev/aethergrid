from app.application.services.worker_heartbeat_service import (
    WorkerHeartbeatService,
)
from app.domain.entities.job import Job
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.enums.worker_status import WorkerStatus
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)


def test_execute_refreshes_worker_heartbeat() -> None:
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = Worker(
        id=WorkerId.new(),
        node=node,
    )

    repository = InMemoryWorkerRepository(
        [
            worker,
        ],
    )

    original = worker.last_seen_at

    service = WorkerHeartbeatService(
        repository,
    )

    service.execute(
        worker.id,
    )

    stored_worker = repository.get_by_id(
        worker.id,
    )

    assert stored_worker is not None
    assert stored_worker.last_seen_at > original


def test_execute_recovers_offline_worker_with_no_running_job() -> None:
    """
    ADR 0041, exercised through the real service/repository path:
    heartbeating an OFFLINE, jobless worker must persist it back to
    IDLE, not just refresh its timestamp.
    """
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = Worker(
        id=WorkerId.new(),
        node=node,
    )
    worker.offline()

    repository = InMemoryWorkerRepository(
        [
            worker,
        ],
    )

    service = WorkerHeartbeatService(
        repository,
    )

    service.execute(
        worker.id,
    )

    stored_worker = repository.get_by_id(
        worker.id,
    )

    assert stored_worker is not None
    assert stored_worker.status is WorkerStatus.IDLE


def test_execute_does_not_recover_offline_worker_with_running_job() -> None:
    """
    ADR 0041's guard, exercised through the real service path: an
    OFFLINE worker holding a job must stay OFFLINE after a heartbeat,
    left for reconciliation to resolve instead.
    """
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = Worker(
        id=WorkerId.new(),
        node=node,
    )

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=1024,
            vram_mib=0,
        ),
    )
    job.queue()
    job.assign_to(node.id)

    worker.ready()
    worker.accept(job)
    worker.offline()

    repository = InMemoryWorkerRepository(
        [
            worker,
        ],
    )

    service = WorkerHeartbeatService(
        repository,
    )

    service.execute(
        worker.id,
    )

    stored_worker = repository.get_by_id(
        worker.id,
    )

    assert stored_worker is not None
    assert stored_worker.status is WorkerStatus.OFFLINE
