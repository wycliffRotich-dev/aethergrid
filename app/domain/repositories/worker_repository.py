from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities.worker import Worker
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.worker_id import WorkerId


class WorkerRepository(ABC):
    """
    Repository contract for persisting workers.
    """

    @abstractmethod
    def save(
        self,
        worker: Worker,
    ) -> None:
        """
        Persist a worker.
        """

    @abstractmethod
    def get_by_id(
        self,
        worker_id: WorkerId,
    ) -> Worker | None:
        """
        Retrieve a worker by its identifier.
        """

    @abstractmethod
    def get_by_node_id(
        self,
        node_id: NodeId,
    ) -> Worker | None:
        """
        Retrieve the worker registered for a node, if one
        exists (ADR 0030). A node has at most one worker at
        any time; this is what registration keys on to
        reclaim an existing worker instead of creating a
        duplicate when an agent restarts.
        """

    @abstractmethod
    def list(
        self,
    ) -> list[Worker]:
        """
        Return every registered worker.
        """

    @abstractmethod
    def delete(
        self,
        worker_id: WorkerId,
    ) -> None:
        """
        Remove a worker.
        """