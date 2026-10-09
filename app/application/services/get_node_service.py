from __future__ import annotations

from app.domain.entities.node import Node
from app.domain.exceptions.node_not_found_error import (
    NodeNotFoundError,
)
from app.domain.repositories.node_repository import (
    NodeRepository,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.tenant_id import TenantId


class GetNodeService:
    """
    Application service responsible for retrieving
    an existing compute node.
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
    ) -> Node:
        """
        Retrieve an existing compute node.

        Args:
            node_id:
                Identifier of the compute node.
            tenant_id:
                Tenant the node must belong to.

        Returns:
            The matching compute node.

        Raises:
            NodeNotFoundError:
                If no compute node exists with the
                given identifier in this tenant.
        """
        node = self._node_repository.get_by_id(
            node_id,
            tenant_id,
        )

        if node is None:
            raise NodeNotFoundError(node_id)

        return node
