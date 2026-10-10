from __future__ import annotations

from ...domain.entities.job import Job
from ...domain.exceptions.job_not_found_error import JobNotFoundError
from ...domain.repositories.job_repository import JobRepository
from ...domain.value_objects.job_id import JobId
from ...domain.value_objects.tenant_id import TenantId


class GetJobService:
    """
    Application service responsible for retrieving
    an existing job.
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
    ) -> Job:
        """
        Retrieve an existing job.

        Args:
            job_id:
                Identifier of the job to retrieve.
            tenant_id:
                Tenant the caller belongs to.

        Returns:
            The matching job.

        Raises:
            JobNotFoundError:
                If no job with the given identifier exists in the
                tenant. A job in another tenant is reported the
                same way.
        """
        job = self._job_repository.get_by_id(
            job_id,
            tenant_id,
        )

        if job is None:
            raise JobNotFoundError(job_id)

        return job
