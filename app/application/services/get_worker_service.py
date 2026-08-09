from __future__ import annotations

from app.domain.entities.worker import Worker
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)
from app.domain.value_objects.worker_id import WorkerId


class GetWorkerService:
    """
    Application service responsible for retrieving
    a single worker.
    """

    def __init__(
        self,
        worker_repository: WorkerRepository,
    ) -> None:
        self._worker_repository = worker_repository

    def execute(
        self,
        worker_id: WorkerId,
    ) -> Worker | None:
        """
        Retrieve a worker by id.

        Returns:
            The worker if found, otherwise None.
        """
        return self._worker_repository.get_by_id(
            worker_id,
        )
