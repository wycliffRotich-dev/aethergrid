from __future__ import annotations

from app.domain.value_objects.worker_id import WorkerId


class WorkerNotFoundError(Exception):
    """
    Raised when a worker with the specified identifier
    cannot be found.
    """

    def __init__(self, worker_id: WorkerId) -> None:
        super().__init__(f"Worker with id '{worker_id}' was not found.")
        self.worker_id = worker_id
