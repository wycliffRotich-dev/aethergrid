from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from app.application.services.record_lease_refusal_service import (
    RecordLeaseRefusalService,
)
from app.domain.entities.lease import DEFAULT_LEASE_DURATION
from app.domain.enums.lease_refusal_operation import LeaseRefusalOperation
from app.domain.enums.lease_refusal_reason import LeaseRefusalReason
from app.domain.exceptions.lease_not_found_error import (
    LeaseNotFoundError,
)
from app.domain.exceptions.no_active_lease_error import (
    NoActiveLeaseError,
)
from app.domain.repositories.lease_repository import (
    LeaseRepository,
)
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId


class RenewLeaseService:
    """
    Extend the lifetime of a worker's active lease.

    Workers periodically renew their lease while executing a
    job. If renewal stops -- or fails, because the lease was
    already reclaimed by reconciliation -- the caller needs to
    know about it, not have the renewal quietly no-op or,
    worse, recreate a lease that's already been handed to
    someone else.

    expected_lease_id (ADR 0038) fences this call against a
    real, previously-unguarded race, the same shape ADR 0034
    closed for release: without it, this method looked up
    whatever lease a worker currently holds by worker_id
    alone and renewed it unconditionally. A stale caller
    whose own lease was already reclaimed by reconciliation,
    with the same worker later legitimately reassigned a new
    lease for a different job, would silently renew that new,
    unrelated lease instead, with no error, potentially
    masking a real reconciliation failure on the legitimate
    job's own renewal path.
    """

    def __init__(
        self,
        lease_repository: LeaseRepository,
        record_lease_refusal_service: RecordLeaseRefusalService | None = None,
    ) -> None:
        self._lease_repository = lease_repository
        self._record_lease_refusal_service = record_lease_refusal_service

    def _record_refusal(
        self,
        worker_id: WorkerId,
        lease_id: UUID,
        tenant_id: TenantId,
        reason: LeaseRefusalReason,
    ) -> None:
        # ADR 0108, decision 5: the record is made just before the
        # refusal is raised, and it never raises itself.
        if self._record_lease_refusal_service is None:
            return

        self._record_lease_refusal_service.record(
            lease_id=lease_id,
            tenant_id=tenant_id,
            worker_id=worker_id,
            operation=LeaseRefusalOperation.RENEW,
            reason=reason,
        )

    def execute(
        self,
        worker_id: WorkerId,
        expected_lease_id: UUID,
        tenant_id: TenantId,
        duration: timedelta = DEFAULT_LEASE_DURATION,
    ) -> None:
        """
        Renew the worker's active lease in this tenant.

        A lease in another tenant is reported exactly like a
        missing one (ADR 0075). The tenant also goes to the
        repository's renew(), so the update cannot reach
        another tenant's lease even if this lookup were wrong.

        Raises:
            NoActiveLeaseError: this worker has no lease on
                record at all -- it never acquired one, or
                reconciliation already reclaimed and removed
                it before this call even looked it up.
            LeaseNotFoundError: whatever lease is on record
                for this worker does not match
                expected_lease_id, meaning reconciliation
                already reclaimed the original lease this
                caller believes it holds, and the worker may
                or may not have since been legitimately
                reassigned a different one (ADR 0038).
        """
        lease = self._lease_repository.get_by_worker_id(
            worker_id,
            tenant_id,
        )

        if lease is None:
            self._record_refusal(
                worker_id,
                expected_lease_id,
                tenant_id,
                LeaseRefusalReason.NO_ACTIVE_LEASE,
            )
            raise NoActiveLeaseError(worker_id)

        if lease.id != expected_lease_id:
            self._record_refusal(
                worker_id,
                expected_lease_id,
                tenant_id,
                LeaseRefusalReason.LEASE_NOT_CURRENT,
            )
            raise LeaseNotFoundError(expected_lease_id)

        self._lease_repository.renew(
            lease.id,
            duration,
            tenant_id,
        )
