from __future__ import annotations

from app.domain.exceptions.node_not_found_error import (
    NodeNotFoundError,
)
from app.domain.exceptions.node_still_alive_error import (
    NodeStillAliveError,
)
from app.domain.repositories.node_repository import (
    NodeRepository,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.tenant_id import TenantId


class RemoveOfflineNodeService:
    """
    Application service responsible for removing
    offline compute nodes.
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
    ) -> None:
        """
        Remove an offline compute node in this tenant.

        Raises:
            NodeNotFoundError:
                If the node does not exist in this tenant.
            NodeStillAliveError:
                If the node is still sending heartbeats.
        """
        node = self._node_repository.get_by_id(
            node_id,
            tenant_id,
        )

        if node is None:
            raise NodeNotFoundError(node_id)

        if node.is_alive():
            raise NodeStillAliveError(
                f"Node {node_id} is still alive and cannot be removed."
            )

        self._node_repository.delete(
            node_id,
            tenant_id,
        )
