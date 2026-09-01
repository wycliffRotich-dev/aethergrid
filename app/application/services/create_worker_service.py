from __future__ import annotations

from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.enums.worker_management import WorkerManagement
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)
from app.domain.value_objects.worker_id import WorkerId


class CreateWorkerService:
    """
    Application service responsible for registering
    a new worker for a compute node.
    """

    def __init__(
        self,
        worker_repository: WorkerRepository,
    ) -> None:
        self._worker_repository = worker_repository

    def execute(
        self,
        node: Node,
        managed_by: WorkerManagement = WorkerManagement.DASHBOARD,
    ) -> Worker:
        """
        Create and persist a worker for a node, or reclaim
        the node's existing worker if one is already
        registered (ADR 0030).

        Reclaiming preserves the existing WorkerId across an
        agent restart rather than minting a new one, using
        Worker.recover(), the same recovery path
        reconciliation already applies to abandoned work.
        """
        existing = self._worker_repository.get_by_node_id(
            node.id,
        )

        if existing is not None:
            existing.recover()
            existing.managed_by = managed_by

            self._worker_repository.save(
                existing,
            )

            return existing

        worker = Worker(
            id=WorkerId.new(),
            node=node,
            managed_by=managed_by,
        )

        worker.ready()

        self._worker_repository.save(
            worker,
        )

        return worker
