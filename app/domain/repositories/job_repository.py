from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities.job import Job
from app.domain.enums.job_status import JobStatus
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId


class JobRepository(ABC):
    """
    Repository abstraction for jobs.
    """

    @abstractmethod
    def save(
        self,
        job: Job,
    ) -> None: ...

    @abstractmethod
    def save_if_leaseless(
        self,
        job: Job,
        expected_status: JobStatus,
    ) -> bool:
        """
        Save the job only if it is still in `expected_status` and no
        lease row points at it, as one step that no other writer can
        interleave with (ADR 0096).

        Return True when the job was saved. Return False, and change
        nothing, when the job is gone, has another status, or has a
        lease. A caller that reads a job, decides to reclaim it and
        then calls save() writes over whatever was saved in between.
        This is the write that cannot, in the spirit of
        LeaseRepository.delete_if_expired (ADR 0034).

        Postgres locks the job row, which also holds back a lease
        insert that references it, and then checks the lease table.
        The in-memory and SQLite backends keep leases in this
        process and are atomic only against writers in this process.
        """
        ...

    @abstractmethod
    def get_by_id(
        self,
        job_id: JobId,
        tenant_id: TenantId,
    ) -> Job | None:
        """
        Retrieve a job in this tenant. A job in another tenant is
        reported exactly like a missing one (ADR 0064, point 5).
        """
        ...

    @abstractmethod
    def list_queued(
        self,
        tenant_id: TenantId,
    ) -> list[Job]:
        """
        Return the queued jobs in this tenant.
        """
        ...

    @abstractmethod
    def list_recent(
        self,
        limit: int,
        tenant_id: TenantId,
    ) -> list[Job]:
        """
        Return the most recently submitted jobs in this tenant,
        ordered newest first, capped at `limit`.

        This is a genuine domain-level query, not a
        persistence detail leaking upward: "give me the
        most recent N jobs" is meaningful vocabulary at the
        repository interface, the same way list_queued()
        already is. Each implementation is responsible for
        pushing the ordering and limit down to its own
        storage engine rather than loading every job into
        memory and discarding most of it.
        """
        ...

    @abstractmethod
    def get_by_id_across_tenants(
        self,
        job_id: JobId,
    ) -> Job | None:
        """
        Retrieve a job in any tenant.

        Reserved for system actors that act on the whole fleet by
        design, and for callers that hold a job id but no tenant
        yet (ADR 0064, point 4). Route-facing code must not use it.
        """
        ...

    @abstractmethod
    def list_across_tenants(
        self,
    ) -> list[Job]:
        """
        List every job in every tenant. System actors only.
        """
        ...
