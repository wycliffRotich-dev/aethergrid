from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities.worker import Worker
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId


class WorkerRepository(ABC):
    """
    Repository contract for persisting workers.

    Every method takes a TenantId or ends in _across_tenants
    (ADR 0064 point 4, ADR 0075 decision 5). A worker in another
    tenant is reported exactly like a missing one (ADR 0064
    point 5). The _across_tenants forms are for system actors
    that act on the whole fleet, or that learn a tenant by
    reading the worker, and every caller of them carries a
    written reason (ADR 0075 decision 10).
    """

    @abstractmethod
    def save(
        self,
        worker: Worker,
    ) -> None:
        """
        Persist a worker.
        """

    @abstractmethod
    def get_by_id(
        self,
        worker_id: WorkerId,
        tenant_id: TenantId,
    ) -> Worker | None:
        """
        Retrieve a worker by its identifier, in this tenant.

        A worker in another tenant is reported as None.
        """

    @abstractmethod
    def get_by_id_across_tenants(
        self,
        worker_id: WorkerId,
    ) -> Worker | None:
        """
        Retrieve a worker by its identifier, in any tenant.

        For system actors that hold a worker id and no tenant,
        such as the worker execution loop, which learns the
        tenant by reading the worker.
        """

    @abstractmethod
    def get_by_node_id(
        self,
        node_id: NodeId,
        tenant_id: TenantId,
    ) -> Worker | None:
        """
        Retrieve the worker registered for a node in this
        tenant, if one exists (ADR 0030). A node has at most
        one worker at any time; this is what registration keys
        on to reclaim an existing worker instead of creating a
        duplicate when an agent restarts.
        """

    @abstractmethod
    def list(
        self,
        tenant_id: TenantId,
    ) -> list[Worker]:
        """
        Return every registered worker in this tenant.
        """

    @abstractmethod
    def list_across_tenants(
        self,
    ) -> list[Worker]:
        """
        Return every registered worker, in every tenant.

        For the system actors that sweep the whole fleet.
        """

    @abstractmethod
    def delete(
        self,
        worker_id: WorkerId,
        tenant_id: TenantId,
    ) -> None:
        """
        Remove a worker in this tenant. A worker in another
        tenant is left untouched, and a missing worker is a
        no-op.
        """
