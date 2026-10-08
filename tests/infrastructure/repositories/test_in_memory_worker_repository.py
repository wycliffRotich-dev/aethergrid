from app.domain.entities.worker import Worker
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)
from tests.support.nodes import make_node


def make_worker(
    worker_id: str,
) -> Worker:
    return Worker(
        id=worker_id,
        node=make_node(
            id=NodeId.new(),
            capacity=ResourceRequirements(
                cpu_cores=8,
                memory_mib=16384,
                vram_mib=0,
            ),
        ),
    )


def test_save_and_get_worker() -> None:
    repository = InMemoryWorkerRepository()

    worker = make_worker(
        "worker-1",
    )

    repository.save(
        worker,
    )

    assert repository.get_by_id(
        "worker-1",
    ) is worker


def test_list_workers() -> None:
    first = make_worker(
        "worker-1",
    )

    second = make_worker(
        "worker-2",
    )

    repository = InMemoryWorkerRepository(
        [
            first,
            second,
        ],
    )

    workers = repository.list()

    assert first in workers
    assert second in workers
    assert len(workers) == 2


def test_delete_worker() -> None:
    worker = make_worker(
        "worker-1",
    )

    repository = InMemoryWorkerRepository(
        [
            worker,
        ],
    )

    repository.delete(
        "worker-1",
    )

    assert repository.get_by_id(
        "worker-1",
    ) is None
