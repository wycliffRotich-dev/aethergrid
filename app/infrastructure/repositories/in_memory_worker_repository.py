from __future__ import annotations

from app.domain.entities.worker import Worker
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)
from app.domain.value_objects.worker_id import WorkerId


class InMemoryWorkerRepository(WorkerRepository):
    """
    In-memory implementation of the WorkerRepository.

    Used by unit tests and local development.
    """

    def __init__(
        self,
        workers: list[Worker] | None = None,
    ) -> None:
        self._workers: dict[WorkerId, Worker] = {}

        for worker in workers or []:
            self.save(worker)

    def save(
        self,
        worker: Worker,
    ) -> None:
        """
        Persist or update a worker.
        """
        self._workers[worker.id] = worker

    def clear(
        self,
    ) -> None:
        """
        Remove every worker. Test-only: lets presentation-layer
        tests reset the shared module-level singleton between
        tests instead of leaking state across the whole suite.
        """
        self._workers.clear()

    def get_by_id(
        self,
        worker_id: WorkerId,
    ) -> Worker | None:
        """
        Retrieve a worker by its identifier.
        """
        return self._workers.get(worker_id)

    def list(
        self,
    ) -> list[Worker]:
        """
        Return every registered worker.
        """
        return list(
            self._workers.values(),
        )

    def delete(
        self,
        worker_id: WorkerId,
    ) -> None:
        """
        Remove a worker.

        The operation is idempotent.
        """
        self._workers.pop(
            worker_id,
            None,
        )