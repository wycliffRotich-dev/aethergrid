from __future__ import annotations

from app.domain.entities.node import Node
from app.domain.repositories.node_repository import (
    NodeRepository,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.tenant_id import TenantId


class HeartbeatNodeService:
    """
    Application service responsible for recording
    a heartbeat from a compute node.
    """

    def __init__(
        self,
        node_repository: NodeRepository,
    ) -> None:
        self._node_repository = node_repository

    def execute(
        self,
        node_id: NodeId,
        tenant_id: TenantId,
    ) -> Node | None:
        """
        Record a heartbeat for a node.

        Returns:
            The updated node if found in this tenant,
            otherwise None.
        """
        node = self._node_repository.get_by_id(
            node_id,
            tenant_id,
        )

        if node is None:
            return None

        node.heartbeat()

        self._node_repository.save(
            node,
        )

        return node
