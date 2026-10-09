from __future__ import annotations

from app.domain.entities.node import Node
from app.domain.exceptions.node_tenant_conflict_error import (
    NodeTenantConflictError,
)
from app.domain.repositories.node_repository import (
    NodeRepository,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.tenant_id import TenantId


class InMemoryNodeRepository(NodeRepository):
    """
    In-memory implementation of the node repository.
    """

    def __init__(
        self,
        nodes: list[Node] | None = None,
    ) -> None:
        self._nodes: dict[NodeId, Node] = {}

        if nodes is not None:
            for node in nodes:
                self.save(node)

    def save(
        self,
        node: Node,
    ) -> None:
        existing = self._nodes.get(node.id)

        if existing is not None and existing.tenant_id != node.tenant_id:
            raise NodeTenantConflictError(
                f"node {node.id} belongs to another tenant"
            )

        self._nodes[node.id] = node

    def clear(
        self,
    ) -> None:
        """
        Remove every node. Test-only: lets presentation-layer
        tests reset the shared module-level singleton between
        tests instead of leaking state across the whole suite.
        """
        self._nodes.clear()

    def list(
        self,
        tenant_id: TenantId,
    ) -> list[Node]:
        return [
            node
            for node in self._nodes.values()
            if node.tenant_id == tenant_id
        ]

    def get_by_id(
        self,
        node_id: NodeId,
        tenant_id: TenantId,
    ) -> Node | None:
        node = self._nodes.get(node_id)

        if node is None or node.tenant_id != tenant_id:
            return None

        return node

    def delete(
        self,
        node_id: NodeId,
        tenant_id: TenantId,
    ) -> None:
        node = self._nodes.get(node_id)

        if node is not None and node.tenant_id == tenant_id:
            del self._nodes[node_id]

    def get_by_id_across_tenants(
        self,
        node_id: NodeId,
    ) -> Node | None:
        return self._nodes.get(
            node_id,
        )

    def list_across_tenants(
        self,
    ) -> list[Node]:
        return list(
            self._nodes.values(),
        )

    def list_available_across_tenants(
        self,
    ) -> list[Node]:
        return [
            node
            for node in self._nodes.values()
            if node.is_alive()
            and not node.is_draining()
        ]
