from __future__ import annotations

from uuid import UUID

from app.domain.entities.lease_reclaim import LeaseReclaim
from app.domain.repositories.lease_reclaim_repository import (
    LeaseReclaimRepository,
)
from app.domain.value_objects.tenant_id import TenantId


class InMemoryLeaseReclaimRepository(
    LeaseReclaimRepository,
):
    """
    In-memory implementation of the LeaseReclaimRepository.
    """

    def __init__(
        self,
    ) -> None:
        self._records: dict[tuple[TenantId, UUID], LeaseReclaim] = {}

    def save(
        self,
        record: LeaseReclaim,
    ) -> None:
        self._records.setdefault(
            (record.tenant_id, record.lease_id),
            record,
        )

    def get_by_lease_id(
        self,
        lease_id: UUID,
        tenant_id: TenantId,
    ) -> LeaseReclaim | None:
        return self._records.get((tenant_id, lease_id))
