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


class DrainNodeService:
    """
    Application service responsible for draining
    compute nodes.
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
        Mark a compute node as draining.

        A draining node continues running any work
        already assigned to it, but the scheduler will
        not assign it new jobs (see Scheduler.eligible_nodes).

        Raises:
            NodeNotFoundError:
                If the node does not exist in this tenant.
        """
        node = self._node_repository.get_by_id(
            node_id,
            tenant_id,
        )

        if node is None:
            raise NodeNotFoundError(node_id)

        node.drain()

        self._node_repository.save(
            node,
        )

        return node
