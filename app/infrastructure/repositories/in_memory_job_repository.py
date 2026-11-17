from __future__ import annotations

import copy
import threading

from app.domain.entities.job import Job
from app.domain.enums.job_status import JobStatus
from app.domain.exceptions.job_tenant_conflict_error import (
    JobTenantConflictError,
)
from app.domain.repositories.job_repository import JobRepository
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId


class InMemoryJobRepository(JobRepository):
    """
    In-memory implementation of the JobRepository.
    """

    def __init__(
        self,
        jobs: list[Job] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}

        if jobs is not None:
            for job in jobs:
                self.save(job)

    def save(
        self,
        job: Job,
    ) -> None:
        with self._lock:
            existing = self._jobs.get(str(job.id))

            if (
                existing is not None
                and existing.tenant_id != job.tenant_id
            ):
                raise JobTenantConflictError(
                    f"job {job.id} belongs to another tenant"
                )

            self._jobs[str(job.id)] = job

    def save_if_unchanged(
        self,
        job: Job,
        expected: Job,
    ) -> bool:
        if job.id != expected.id or job.tenant_id != expected.tenant_id:
            raise ValueError(
                "expected snapshot must share id and tenant_id with job"
            )

        with self._lock:
            existing = self._jobs.get(str(job.id))

            if existing is None:
                return False

            if existing.tenant_id != job.tenant_id:
                raise JobTenantConflictError(
                    f"job {job.id} belongs to another tenant"
                )

            if not _lifecycle_matches(existing, expected):
                return False

            if existing is not job:
                for slot in Job.__slots__:
                    setattr(
                        existing,
                        slot,
                        copy.deepcopy(getattr(job, slot)),
                    )

            return True

    def clear(
        self,
    ) -> None:
        """
        Remove every job. Test-only: lets presentation-layer
        tests reset the shared module-level singleton between
        tests instead of leaking state across the whole suite.
        """
        with self._lock:
            self._jobs.clear()

    def get_by_id(
        self,
        job_id: JobId,
        tenant_id: TenantId,
    ) -> Job | None:
        with self._lock:
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
        with self._lock:
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
        with self._lock:
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
        with self._lock:
            return self._jobs.get(
                str(job_id),
            )

    def list_across_tenants(
        self,
    ) -> list[Job]:
        with self._lock:
            return list(
                self._jobs.values(),
            )


def _lifecycle_matches(
    stored: Job,
    expected: Job,
) -> bool:
    return (
        stored.status == expected.status
        and stored.retry_count == expected.retry_count
        and stored.assigned_node_id == expected.assigned_node_id
        and stored.started_at == expected.started_at
        and stored.completed_at == expected.completed_at
        and stored.exit_code == expected.exit_code
        and stored.cancellation_requested_at
        == expected.cancellation_requested_at
    )
