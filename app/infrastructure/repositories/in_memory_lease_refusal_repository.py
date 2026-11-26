from __future__ import annotations

from uuid import UUID

from app.domain.entities.lease_refusal import LeaseRefusal
from app.domain.enums.lease_refusal_operation import LeaseRefusalOperation
from app.domain.enums.lease_refusal_reason import LeaseRefusalReason
from app.domain.repositories.lease_refusal_repository import (
    LeaseRefusalRepository,
)
from app.domain.value_objects.tenant_id import TenantId

_Key = tuple[TenantId, UUID, LeaseRefusalOperation, LeaseRefusalReason]


class InMemoryLeaseRefusalRepository(
    LeaseRefusalRepository,
):
    """
    In-memory implementation of the LeaseRefusalRepository.
    """

    def __init__(
        self,
    ) -> None:
        self._refusals: dict[_Key, LeaseRefusal] = {}

    def save(
        self,
        refusal: LeaseRefusal,
    ) -> None:
        self._refusals.setdefault(
            (
                refusal.tenant_id,
                refusal.lease_id,
                refusal.operation,
                refusal.reason,
            ),
            refusal,
        )

    def list_for_lease(
        self,
        lease_id: UUID,
        tenant_id: TenantId,
    ) -> list[LeaseRefusal]:
        return sorted(
            (
                refusal
                for refusal in self._refusals.values()
                if refusal.tenant_id == tenant_id
                and refusal.lease_id == lease_id
            ),
            key=lambda refusal: refusal.refused_at,
        )
