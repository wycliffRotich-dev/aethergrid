from __future__ import annotations

from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
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
    ) -> Worker:
        """
        Create and persist a worker.
        """
        worker = Worker(
            id=WorkerId.new(),
            node=node,
        )

        worker.ready()

        self._worker_repository.save(
            worker,
        )

        return worker
