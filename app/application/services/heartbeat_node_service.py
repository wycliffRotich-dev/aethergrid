from __future__ import annotations

from app.domain.entities.node import Node, utc_now
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

        Only the heartbeat time is written. The node is not read,
        changed and saved as a whole, because that would write its
        capacity figures back over any allocation the scheduler
        made in between, and the node would then offer capacity
        that is already promised.

        Returns:
            The node as stored after the heartbeat if found in
            this tenant, otherwise None.
        """
        recorded = self._node_repository.record_heartbeat(
            node_id,
            tenant_id,
            utc_now(),
        )

        if not recorded:
            return None

        return self._node_repository.get_by_id(
            node_id,
            tenant_id,
        )
