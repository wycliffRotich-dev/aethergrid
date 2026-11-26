from __future__ import annotations

import logging
from uuid import UUID

from app.domain.entities.lease_refusal import LeaseRefusal
from app.domain.enums.lease_refusal_operation import LeaseRefusalOperation
from app.domain.enums.lease_refusal_reason import LeaseRefusalReason
from app.domain.repositories.lease_reclaim_repository import (
    LeaseReclaimRepository,
)
from app.domain.repositories.lease_refusal_repository import (
    LeaseRefusalRepository,
)
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId

logger = logging.getLogger(__name__)


class RecordLeaseRefusalService:
    """
    Application service that keeps the record of a renew or a release that
    lease fencing refused (ADR 0108, decisions 4 and 5).

    Only a lease that reclaim removed is recorded, so the service reads the
    reclaim record of the lease id in the tenant first and records nothing
    when there is none. A failed read or a failed save is logged as one
    warning and is not raised, so a failed write cannot change the refusal
    that the caller gets.
    """

    def __init__(
        self,
        lease_reclaim_repository: LeaseReclaimRepository,
        lease_refusal_repository: LeaseRefusalRepository,
    ) -> None:
        self._lease_reclaim_repository = lease_reclaim_repository
        self._lease_refusal_repository = lease_refusal_repository

    def record(
        self,
        *,
        lease_id: UUID,
        tenant_id: TenantId,
        worker_id: WorkerId,
        operation: LeaseRefusalOperation,
        reason: LeaseRefusalReason,
    ) -> None:
        """
        Save the refusal of this call when the lease it named was reclaimed.
        """
        try:
            reclaim = self._lease_reclaim_repository.get_by_lease_id(
                lease_id,
                tenant_id,
            )

            if reclaim is None:
                return

            self._lease_refusal_repository.save(
                LeaseRefusal.record(
                    reclaim=reclaim,
                    worker_id=worker_id,
                    operation=operation,
                    reason=reason,
                )
            )
        except Exception as error:
            logger.warning(
                "The record of the refused %s of lease %s was not saved: %s",
                operation,
                lease_id,
                error,
            )
