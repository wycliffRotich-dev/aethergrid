from __future__ import annotations

from app.domain.entities.node import Node
from app.domain.repositories.node_repository import (
    NodeRepository,
)


class ListNodesService:
    """
    Application service responsible for listing every
    registered compute node.
    """

    def __init__(
        self,
        node_repository: NodeRepository,
    ) -> None:
        self._node_repository = node_repository

    def execute(
        self,
    ) -> list[Node]:
        """
        Retrieve every registered compute node, regardless
        of whether it is currently alive.

        Previously this filtered to only alive nodes, which
        meant a node that missed its heartbeat vanished from
        this list entirely rather than appearing as offline.
        That produced a dashboard where ClusterHealthService
        correctly reported "1 node, offline" while this list
        simultaneously reported zero nodes registered.
        Callers that specifically need only offline nodes
        should use ListOfflineNodesService instead.
        """
        return list(self._node_repository.list())
