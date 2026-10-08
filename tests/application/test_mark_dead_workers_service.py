from datetime import timedelta

from app.application.services.mark_dead_workers_service import (
    MarkDeadWorkersService,
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


def test_execute_marks_expired_workers_offline() -> None:
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

    worker.ready()

    worker.last_seen_at = (
        worker.last_seen_at - timedelta(minutes=2)
    )

    repository = InMemoryWorkerRepository(
        [
            worker,
        ],
    )

    service = MarkDeadWorkersService(
        worker_repository=repository,
    )

    service.execute()

    saved_worker = repository.get_by_id(
        worker.id,
    )

    assert saved_worker is not None
    assert saved_worker.is_offline()
