from __future__ import annotations

from app.domain.entities.job import Job
from app.domain.repositories.job_repository import (
    JobRepository,
)
from app.domain.value_objects.tenant_id import TenantId


class ListQueuedJobsService:
    """
    Application service responsible for
    listing queued jobs.
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
        """
        Return the queued jobs in this tenant.
        """
        return self._job_repository.list_queued(tenant_id)
