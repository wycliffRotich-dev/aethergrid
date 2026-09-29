from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta
from uuid import UUID

from app.domain.entities.lease import Lease
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.worker_id import WorkerId


class LeaseRepository(ABC):
    """
    Repository contract for managing leases.

    A lease represents temporary ownership of a job by a
    worker. Implementations may store leases in memory,
    SQLite, PostgreSQL, or any other persistence backend.
    """

    @abstractmethod
    def save(
        self,
        lease: Lease,
    ) -> None:
        """
        Persist a lease, creating it if it doesn't already
        exist.

        This is the acquire-time path -- AcquireLeaseService
        calls this for a lease that has never existed before.
        It is deliberately permissive: it doesn't check
        whether the row is already there. Renewing an
        existing lease should go through renew() instead,
        which fails loudly rather than silently recreating a
        lease someone else already reclaimed.
        """
        raise NotImplementedError

    @abstractmethod
    def renew(
        self,
        lease_id: UUID,
        duration: timedelta,
    ) -> None:
        """
        Extend an existing lease's expiry in place.

        Raises LeaseNotFoundError if no lease with this id
        currently exists. This must never fall back to
        creating a new row -- a renewal racing reconciliation's
        delete of the same lease needs to fail, not resurrect
        a lease that's already been handed to someone else.
        """
        raise NotImplementedError

    @abstractmethod
    def get_by_job_id(
        self,
        job_id: JobId,
    ) -> Lease | None:
        """
        Return the lease for a job.

        Returns None when no lease exists.
        """
        raise NotImplementedError

    @abstractmethod
    def get_by_worker_id(
        self,
        worker_id: WorkerId,
    ) -> Lease | None:
        """
        Return the lease owned by a worker.

        Returns None when the worker owns no lease.
        """
        raise NotImplementedError

    @abstractmethod
    def list(
        self,
    ) -> list[Lease]:
        """
        Return all leases.
        """
        raise NotImplementedError

    @abstractmethod
    def delete(
        self,
        job_id: JobId,
    ) -> None:
        """
        Remove a lease by job id, unconditionally.
        """
        raise NotImplementedError

    @abstractmethod
    def delete_if_expired(
        self,
        job_id: JobId,
    ) -> bool:
        """
        Delete the lease for job_id only if it is still
        expired at the moment of deletion, not merely at some
        earlier read. Returns True if a row was deleted,
        False if no lease exists for job_id or the lease was
        renewed since the caller last checked.

        Exists because a caller (reconciliation) may check
        is_expired() against a snapshot read, then act on
        that snapshot later. Between the read and the delete,
        a worker's renewal thread may have legitimately
        extended the lease. Without this check, delete()
        would remove a lease the worker now legitimately
        owns -- the same class of bug ADR 0034 fenced for
        release, applied here to reconciliation's own reclaim
        path, which ADR 0034-0038 never covered.
        """
        raise NotImplementedError
