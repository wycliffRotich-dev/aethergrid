from app.application.services.worker_heartbeat_service import (
    WorkerHeartbeatService,
)
from app.application.workers.worker_heartbeat_loop import (
    WorkerHeartbeatLoop,
)
from app.domain.entities.worker import Worker
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)
from tests.support.nodes import make_node


def test_run_once_sends_heartbeat() -> None:
    node = make_node(
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

    heartbeat_service = WorkerHeartbeatService(
        worker_repository=repository,
    )

    loop = WorkerHeartbeatLoop(
        heartbeat_service=heartbeat_service,
        worker_id=worker.id,
    )

    previous = worker.last_seen_at

    loop.run_once()

    saved = repository.get_by_id(
        worker.id,
    )

    assert saved is not None
    assert saved.last_seen_at > previous
