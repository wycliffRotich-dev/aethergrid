from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from app.domain.entities.lease import utc_now
from app.domain.entities.lease_reclaim import LeaseReclaim
from app.domain.enums.lease_refusal_operation import LeaseRefusalOperation
from app.domain.enums.lease_refusal_reason import LeaseRefusalReason
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId


@dataclass(frozen=True, slots=True)
class LeaseRefusal:
    """
    The record of a renew or a release that was refused because the lease
    it named is a lease that reclaim removed (ADR 0108).

    The tenant, the lease id and the job id come from the record of the
    reclaim (ADR 0107), so a refusal can only name a lease that was held
    and then removed. The worker is the one that made the refused call,
    and it can differ from the worker of the removed lease.

    Immutable. A record is written once and never changed.
    """

    id: UUID
    tenant_id: TenantId
    lease_id: UUID
    worker_id: WorkerId
    job_id: JobId
    operation: LeaseRefusalOperation
    reason: LeaseRefusalReason
    refused_at: datetime

    @classmethod
    def record(
        cls,
        *,
        reclaim: LeaseReclaim,
        worker_id: WorkerId,
        operation: LeaseRefusalOperation,
        reason: LeaseRefusalReason,
    ) -> LeaseRefusal:
        """
        Record a refused call against a reclaimed lease. The reclaim
        record is only read, and refused_at is the time of the call.
        """
        return cls(
            id=uuid4(),
            tenant_id=reclaim.tenant_id,
            lease_id=reclaim.lease_id,
            worker_id=worker_id,
            job_id=reclaim.job_id,
            operation=operation,
            reason=reason,
            refused_at=utc_now(),
        )
