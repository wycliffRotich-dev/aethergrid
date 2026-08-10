from __future__ import annotations

from datetime import timedelta

from app.domain.entities.lease import DEFAULT_LEASE_DURATION
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
    """

    def __init__(
        self,
        lease_repository: LeaseRepository,
    ) -> None:
        self._lease_repository = lease_repository

    def execute(
        self,
        worker_id: WorkerId,
        duration: timedelta = DEFAULT_LEASE_DURATION,
    ) -> None:
        """
        Renew the worker's active lease.

        Raises:
            NoActiveLeaseError: this worker has no lease on
                record at all -- it never acquired one, or
                reconciliation already reclaimed and removed
                it before this call even looked it up.
            LeaseNotFoundError: the lease was found by this
                call's own lookup, but the underlying row was
                deleted by reconciliation in the narrow window
                between that lookup and the actual renew,
                raised by the repository, not this service.
        """
        lease = self._lease_repository.get_by_worker_id(
            worker_id,
        )

        if lease is None:
            raise NoActiveLeaseError(worker_id)

        self._lease_repository.renew(
            lease.id,
            duration,
        )
