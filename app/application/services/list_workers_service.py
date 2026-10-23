from __future__ import annotations

from app.domain.entities.worker import Worker
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)
from app.domain.value_objects.tenant_id import TenantId


class ListWorkersService:
    """
    Lists all registered workers.
    """

    def __init__(
        self,
        worker_repository: WorkerRepository,
    ) -> None:
        self._worker_repository = worker_repository

    def execute(
        self,
        tenant_id: TenantId,
    ) -> list[Worker]:
        """
        Return the registered workers that belong to tenant_id.

        A worker belongs to the tenant of its node (ADR 0064
        point 5).
        """
        return [
            worker
            for worker in self._worker_repository.list(tenant_id)
            if worker.node.tenant_id == tenant_id
        ]
