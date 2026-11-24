from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from app.domain.entities.lease import Lease, utc_now
from app.domain.enums.lease_recovery_path import LeaseRecoveryPath
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId


@dataclass(frozen=True, slots=True)
class LeaseReclaim:
    """
    The record of a lease that a recovery path deleted while it
    reclaimed a job (ADR 0107).

    A lease row is gone after reclaim, so this keeps what the row held:
    its id, worker, job, tenant and both times. The record has an id of
    its own, and lease_id is the id of the lease that was deleted.

    Immutable. A record is written once and never changed.
    """

    id: UUID
    tenant_id: TenantId
    lease_id: UUID
    worker_id: WorkerId
    job_id: JobId
    lease_acquired_at: datetime
    lease_expires_at: datetime
    reclaimed_at: datetime
    recovered_by: LeaseRecoveryPath

    @classmethod
    def record(
        cls,
        *,
        lease: Lease,
        recovered_by: LeaseRecoveryPath,
    ) -> LeaseReclaim:
        """
        Record the deletion of this lease. The lease is only read, and
        reclaimed_at is the time of the call.
        """
        return cls(
            id=uuid4(),
            tenant_id=lease.tenant_id,
            lease_id=lease.id,
            worker_id=lease.worker_id,
            job_id=lease.job_id,
            lease_acquired_at=lease.acquired_at,
            lease_expires_at=lease.expires_at,
            reclaimed_at=utc_now(),
            recovered_by=recovered_by,
        )
