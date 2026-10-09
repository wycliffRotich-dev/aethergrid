from __future__ import annotations

from app.domain.entities.node import Node
from app.domain.repositories.node_repository import (
    NodeRepository,
)
from app.domain.value_objects.tenant_id import TenantId


class ListOfflineNodesService:
    """
    Application service responsible for listing
    offline compute nodes.
    """

    def __init__(
        self,
        node_repository: NodeRepository,
    ) -> None:
        self._node_repository = node_repository

    def execute(
        self,
        tenant_id: TenantId,
    ) -> list[Node]:
        """
        Retrieve all offline compute nodes in this tenant.
        """
        return [
            node
            for node in self._node_repository.list(tenant_id)
            if not node.is_alive()
        ]
