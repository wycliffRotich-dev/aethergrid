from __future__ import annotations

from app.domain.entities.worker import Worker
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)
from app.domain.value_objects.worker_id import WorkerId


class WorkerHeartbeatService:
    """
    Refresh the heartbeat timestamp for a worker.
    """

    def __init__(
        self,
        worker_repository: WorkerRepository,
    ) -> None:
        self._worker_repository = worker_repository

    def execute(
        self,
        worker_id: WorkerId,
    ) -> Worker:
        """
        Record that the worker is alive.

        Returns the updated worker.
        """
        worker = self._worker_repository.get_by_id(
            worker_id,
        )

        if worker is None:
            raise ValueError(
                "Worker does not exist."
            )

        worker.heartbeat()

        self._worker_repository.save(
            worker,
        )

        return worker
