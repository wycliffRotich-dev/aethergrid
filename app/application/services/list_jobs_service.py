from __future__ import annotations

from app.domain.entities.job import Job
from app.domain.repositories.job_repository import (
    JobRepository,
)
from app.domain.value_objects.tenant_id import TenantId

MAX_JOBS_RETURNED = 50


class ListJobsService:
    """
    Return the most recently submitted jobs.

    Capped at MAX_JOBS_RETURNED rather than paginated: this
    is a monitoring dashboard, not a paginated job browser.
    Ordering and the limit are enforced by the repository,
    against its own storage engine, not recomputed here.
    """

    def __init__(
        self,
        job_repository: JobRepository,
    ) -> None:
        self._job_repository = job_repository

    def execute(
        self,
        tenant_id: TenantId,
    ) -> list[Job]:
        return self._job_repository.list_recent(
            MAX_JOBS_RETURNED,
            tenant_id,
        )
