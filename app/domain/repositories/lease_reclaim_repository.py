from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.lease_reclaim import LeaseReclaim
from app.domain.value_objects.tenant_id import TenantId


class LeaseReclaimRepository(ABC):
    """
    Repository contract for the records of leases that a recovery path
    deleted while it reclaimed a job (ADR 0107).

    A record is written once and never changed. Implementations may keep
    records in memory or in PostgreSQL.
    """

    @abstractmethod
    def save(
        self,
        record: LeaseReclaim,
    ) -> None:
        """
        Persist a record. A record already kept for the same lease in the
        same tenant is left as it is, and nothing is raised: the first
        record of a lease stays.
        """
        raise NotImplementedError

    @abstractmethod
    def get_by_lease_id(
        self,
        lease_id: UUID,
        tenant_id: TenantId,
    ) -> LeaseReclaim | None:
        """
        Return the record of this lease in this tenant, or None. A record
        in another tenant is reported exactly like a missing one
        (ADR 0064, point 5).
        """
        raise NotImplementedError
