from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.lease_refusal import LeaseRefusal
from app.domain.value_objects.tenant_id import TenantId


class LeaseRefusalRepository(ABC):
    """
    Repository contract for the records of renews and releases that lease
    fencing refused (ADR 0108).

    A record is written once and never changed. Implementations may keep
    records in memory or in PostgreSQL.
    """

    @abstractmethod
    def save(
        self,
        refusal: LeaseRefusal,
    ) -> None:
        """
        Persist a record. A record already kept for the same lease, the
        same operation and the same reason in the same tenant is left as
        it is, and nothing is raised: the first refusal of each kind stays.
        """
        raise NotImplementedError

    @abstractmethod
    def list_for_lease(
        self,
        lease_id: UUID,
        tenant_id: TenantId,
    ) -> list[LeaseRefusal]:
        """
        Return the records of this lease in this tenant, oldest first. A
        record in another tenant is reported exactly like a missing one
        (ADR 0064, point 5).
        """
        raise NotImplementedError
