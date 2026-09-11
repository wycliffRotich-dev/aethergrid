from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from app.domain.entities.lease import DEFAULT_LEASE_DURATION
from app.domain.exceptions.lease_not_found_error import (
    LeaseNotFoundError,
)
from app.domain.exceptions.no_active_lease_error import (
    NoActiveLeaseError,
)
from app.domain.repositories.lease_repository import (
    LeaseRepository,
)
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
    ) -> None:
        self._lease_repository = lease_repository

    def execute(
        self,
        worker_id: WorkerId,
        expected_lease_id: UUID,
        duration: timedelta = DEFAULT_LEASE_DURATION,
    ) -> None:
        """
        Renew the worker's active lease.

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
        )

        if lease is None:
            raise NoActiveLeaseError(worker_id)

        if lease.id != expected_lease_id:
            raise LeaseNotFoundError(expected_lease_id)

        self._lease_repository.renew(
            lease.id,
            duration,
        )
