from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities.node import Node
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.tenant_id import TenantId


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
        tenant_id: TenantId,
    ) -> list[Node]:
        """
        List the nodes in this tenant.
        """
        ...

    @abstractmethod
    def get_by_id(
        self,
        node_id: NodeId,
        tenant_id: TenantId,
    ) -> Node | None:
        """
        Retrieve a node in this tenant. A node in another tenant is
        reported exactly like a missing one (ADR 0064, point 5).
        """
        ...

    @abstractmethod
    def delete(
        self,
        node_id: NodeId,
        tenant_id: TenantId,
    ) -> None:
        """
        Remove a node from this tenant. A node in another tenant is
        left untouched, and a missing node is a no-op.
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
