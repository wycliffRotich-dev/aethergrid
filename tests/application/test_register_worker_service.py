from app.application.services.register_worker_service import (
    RegisterWorkerService,
)
from app.domain.entities.worker import Worker
from app.domain.enums.worker_status import WorkerStatus
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from tests.support.nodes import make_node


class InMemoryWorkerRepository:
    """
    Minimal in-memory repository used for
    application-service testing.
    """

    def __init__(self) -> None:
        self._workers: dict[str, Worker] = {}

    def save(
        self,
        worker: Worker,
    ) -> None:
        self._workers[worker.id] = worker

    def get_by_id(
        self,
        worker_id: str,
    ) -> Worker | None:
        return self._workers.get(worker_id)

    def list(
        self,
    ) -> list[Worker]:
        return list(self._workers.values())


def test_register_worker_service_registers_worker() -> None:
    repository = InMemoryWorkerRepository()

    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16_384,
            vram_mib=0,
        ),
    )

    worker = Worker(
        id="worker-1",
        node=node,
    )

    service = RegisterWorkerService(
        repository,
    )

    registered = service.execute(
        worker,
    )

    assert registered is worker
    assert registered.status is WorkerStatus.IDLE
    assert repository.get_by_id("worker-1") is worker
