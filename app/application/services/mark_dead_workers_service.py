from __future__ import annotations

from app.domain.repositories.worker_repository import (
    WorkerRepository,
)


class MarkDeadWorkersService:
    """
    Mark workers as OFFLINE when they have not sent
    a heartbeat within the configured timeout.
    """

    def __init__(
        self,
        worker_repository: WorkerRepository,
    ) -> None:
        self._worker_repository = worker_repository

    def execute(
        self,
    ) -> None:
        """
        Scan every registered worker and mark stale
        workers as offline.
        """
        for worker in self._worker_repository.list_across_tenants():
            if worker.is_alive():
                continue

            worker.offline()

            self._worker_repository.save(
                worker,
            )
