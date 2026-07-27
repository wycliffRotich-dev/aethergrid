from __future__ import annotations

from app.domain.entities.node import Node
from app.domain.repositories.node_repository import (
    NodeRepository,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)


class CreateNodeService:
    """
    Application service responsible for creating
    and persisting compute nodes.
    """

    def __init__(
        self,
        node_repository: NodeRepository,
    ) -> None:
        self._node_repository = node_repository

    def execute(
        self,
        capacity: ResourceRequirements,
        name: str | None = None,
    ) -> Node:
        """
        Create and persist a new compute node.

        If name is not supplied, Node generates its own
        human-friendly fallback name. A real node agent is
        expected to supply its own hostname here; the
        fallback exists for nodes registered without one,
        such as through manual registration.

        Returns:
            The newly created node.
        """
        node = (
            Node(
                id=NodeId.new(),
                capacity=capacity,
                name=name,
            )
            if name
            else Node(
                id=NodeId.new(),
                capacity=capacity,
            )
        )

        self._node_repository.save(node)

        return node
