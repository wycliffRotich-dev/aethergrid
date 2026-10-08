from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities.node import Node
from app.domain.value_objects.node_id import NodeId


class NodeRepository(ABC):
    """
    Repository abstraction for compute nodes.
    """

    @abstractmethod
    def save(
        self,
        node: Node,
    ) -> None: ...

    @abstractmethod
    def list(
        self,
    ) -> list[Node]: ...

    @abstractmethod
    def list_available(
        self,
    ) -> list[Node]: ...

    @abstractmethod
    def get_by_id(
        self,
        node_id: NodeId,
    ) -> Node | None: ...

    @abstractmethod
    def delete(
        self,
        node_id: NodeId,
    ) -> None:
        """
        Remove a node from the repository.
        """
        ...

    @abstractmethod
    def get_by_id_across_tenants(
        self,
        node_id: NodeId,
    ) -> Node | None:
        """
        Retrieve a node in any tenant.

        Reserved for system actors that act on the whole fleet by
        design, and for callers that hold a node id but no tenant
        yet (ADR 0064, point 4). Route-facing code must not use it.
        """
        ...

    @abstractmethod
    def list_across_tenants(
        self,
    ) -> list[Node]:
        """
        List every node in every tenant. System actors only.
        """
        ...

    @abstractmethod
    def list_available_across_tenants(
        self,
    ) -> list[Node]:
        """
        List nodes that are eligible for scheduling, in every
        tenant. System actors only.
        """
        ...
