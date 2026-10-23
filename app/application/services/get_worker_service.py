from __future__ import annotations

from app.domain.entities.worker import Worker
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)
from app.domain.value_objects.tenant_id import TenantId
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
        tenant_id: TenantId,
    ) -> Worker | None:
        """
        Retrieve a worker by id, if it belongs to tenant_id.

        A worker has no tenant of its own yet, so it belongs to
        the tenant of its node. A worker in another tenant is
        indistinguishable from one that does not exist (ADR 0064
        point 5).

        Returns:
            The worker if found in this tenant, otherwise None.
        """
        worker = self._worker_repository.get_by_id(
            worker_id,
            tenant_id,
        )

        if worker is None or worker.node.tenant_id != tenant_id:
            return None

        return worker
