from __future__ import annotations

import builtins

from app.domain.entities.worker import Worker
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.tenant_id import TenantId
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
        tenant_id: TenantId,
    ) -> Worker | None:
        """
        Retrieve a worker by its identifier, in this tenant.
        """
        worker = self._workers.get(worker_id)

        if worker is None or worker.tenant_id != tenant_id:
            return None

        return worker

    def get_by_id_across_tenants(
        self,
        worker_id: WorkerId,
    ) -> Worker | None:
        """
        Retrieve a worker by its identifier, in any tenant.
        """
        return self._workers.get(worker_id)

    def get_by_node_id(
        self,
        node_id: NodeId,
        tenant_id: TenantId,
    ) -> Worker | None:
        """
        Retrieve the worker registered for a node in this
        tenant, if one exists (ADR 0030).
        """
        for worker in self._workers.values():
            if worker.node.id == node_id and worker.tenant_id == tenant_id:
                return worker

        return None

    def list(
        self,
        tenant_id: TenantId,
    ) -> list[Worker]:
        """
        Return every registered worker in this tenant.
        """
        return [
            worker
            for worker in self._workers.values()
            if worker.tenant_id == tenant_id
        ]

    def list_across_tenants(
        self,
    ) -> builtins.list[Worker]:
        """
        Return every registered worker, in every tenant.
        """
        return list(
            self._workers.values(),
        )

    def delete(
        self,
        worker_id: WorkerId,
        tenant_id: TenantId,
    ) -> None:
        """
        Remove a worker in this tenant.

        The operation is idempotent. A worker in another
        tenant is left untouched.
        """
        worker = self._workers.get(worker_id)

        if worker is not None and worker.tenant_id == tenant_id:
            del self._workers[worker_id]
