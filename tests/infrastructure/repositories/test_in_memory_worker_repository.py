from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)
from tests.support.workers import make_worker


def test_save_and_get_worker() -> None:
    repository = InMemoryWorkerRepository()

    worker = make_worker(
        id="worker-1",
    )

    repository.save(
        worker,
    )

    assert repository.get_by_id(
        "worker-1",
    ) is worker


def test_list_workers() -> None:
    first = make_worker(
        id="worker-1",
    )

    second = make_worker(
        id="worker-2",
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
        id="worker-1",
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
