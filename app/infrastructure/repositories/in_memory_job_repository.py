from __future__ import annotations

from app.domain.entities.job import Job
from app.domain.enums.job_status import JobStatus
from app.domain.exceptions.job_tenant_conflict_error import (
    JobTenantConflictError,
)
from app.domain.repositories.job_repository import JobRepository
from app.domain.repositories.lease_repository import LeaseRepository
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId


class InMemoryJobRepository(JobRepository):
    """
    In-memory implementation of the JobRepository.
    """

    def __init__(
        self,
        jobs: list[Job] | None = None,
        lease_repository: LeaseRepository | None = None,
    ) -> None:
        self._jobs: dict[str, Job] = {}
        # Needed only by save_if_leaseless: leases live in another
        # repository here, and the fence has to see them.
        self._lease_repository = lease_repository

        if jobs is not None:
            for job in jobs:
                self.save(job)

    def save(
        self,
        job: Job,
    ) -> None:
        existing = self._jobs.get(str(job.id))

        if existing is not None and existing.tenant_id != job.tenant_id:
            raise JobTenantConflictError(
                f"job {job.id} belongs to another tenant"
            )

        self._jobs[str(job.id)] = job

    def save_if_leaseless(
        self,
        job: Job,
        expected_status: JobStatus,
    ) -> bool:
        if self._lease_repository is None:
            raise RuntimeError(
                "save_if_leaseless needs the lease repository this "
                "repository was built without"
            )

        existing = self._jobs.get(str(job.id))

        if (
            existing is None
            or existing.tenant_id != job.tenant_id
            or existing.status is not expected_status
        ):
            return False

        if (
            self._lease_repository.get_by_job_id(job.id, job.tenant_id)
            is not None
        ):
            return False

        self._jobs[str(job.id)] = job
        return True

    def clear(
        self,
    ) -> None:
        """
        Remove every job. Test-only: lets presentation-layer
        tests reset the shared module-level singleton between
        tests instead of leaking state across the whole suite.
        """
        self._jobs.clear()

    def get_by_id(
        self,
        job_id: JobId,
        tenant_id: TenantId,
    ) -> Job | None:
        job = self._jobs.get(str(job_id))

        if job is None or job.tenant_id != tenant_id:
            return None

        return job

    def list_queued(
        self,
        tenant_id: TenantId,
    ) -> list[Job]:
        """
        Return the queued jobs in this tenant.
        """
        return [
            job
            for job in self._jobs.values()
            if job.tenant_id == tenant_id
            and job.status == JobStatus.QUEUED
        ]

    def list_recent(
        self,
        limit: int,
        tenant_id: TenantId,
    ) -> list[Job]:
        """
        Return the most recently submitted jobs in this tenant,
        newest first, capped at `limit`.
        """
        return sorted(
            (
                job
                for job in self._jobs.values()
                if job.tenant_id == tenant_id
            ),
            key=lambda job: job.submitted_at,
            reverse=True,
        )[:limit]

    def get_by_id_across_tenants(
        self,
        job_id: JobId,
    ) -> Job | None:
        return self._jobs.get(
            str(job_id),
        )

    def list_across_tenants(
        self,
    ) -> list[Job]:
        return list(
            self._jobs.values(),
        )
