from __future__ import annotations

from app.domain.entities.worker import Worker
from app.domain.exceptions.worker_not_found_error import (
    WorkerNotFoundError,
)
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)
from app.domain.value_objects.tenant_id import TenantId
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
        tenant_id: TenantId,
    ) -> Worker:
        """
        Record that the worker is alive.

        A worker in another tenant is indistinguishable from one
        that does not exist (ADR 0064 point 5, ADR 0073): both
        raise WorkerNotFoundError, and the ownership check runs
        before heartbeat() so a foreign call changes nothing.

        Returns the updated worker.
        """
        worker = self._worker_repository.get_by_id(
            worker_id,
            tenant_id,
        )

        if worker is None or not worker.belongs_to(tenant_id):
            raise WorkerNotFoundError(worker_id)

        worker.heartbeat()

        self._worker_repository.save(
            worker,
        )

        return worker
