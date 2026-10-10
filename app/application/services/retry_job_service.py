from __future__ import annotations

from app.domain.entities.job import Job
from app.domain.enums.job_status import JobStatus
from app.domain.repositories.job_repository import (
    JobRepository,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId


class RetryJobService:
    """
    Requeue failed jobs that still
    have retries remaining.
    """

    def __init__(
        self,
        job_repository: JobRepository,
    ) -> None:
        self._job_repository = job_repository

    def execute(
        self,
        job_id: JobId,
        tenant_id: TenantId,
    ) -> Job | None:
        """
        Retry a failed job if it still has
        retries remaining.

        Returns:
            The updated job if found in the tenant,
            otherwise None.
        """
        job = self._job_repository.get_by_id(
            job_id,
            tenant_id,
        )

        if job is None:
            return None

        if job.status != JobStatus.FAILED:
            return job

        if not job.can_retry():
            return job

        job.retry()

        self._job_repository.save(
            job,
        )

        return job
