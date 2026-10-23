from __future__ import annotations

from app.domain.entities.job import Job
from app.domain.repositories.job_repository import JobRepository
from app.domain.repositories.node_repository import NodeRepository
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId


class CompleteJobService:
    """
    Application service responsible for completing a job
    and releasing the resources allocated on its node.
    """

    def __init__(
        self,
        job_repository: JobRepository,
        node_repository: NodeRepository,
    ) -> None:
        self._job_repository = job_repository
        self._node_repository = node_repository

    def execute(
        self,
        job_id: JobId,
        tenant_id: TenantId,
    ) -> Job | None:
        """
        Complete a running job in this tenant.

        The job and its node are both read in tenant_id. A job or
        node in another tenant reads as missing, and nothing changes
        (ADR 0075 decision 10).

        Returns:
            The completed job if found, otherwise None.
        """
        job = self._job_repository.get_by_id(job_id, tenant_id)

        if job is None:
            return None

        if job.assigned_node_id is None:
            return None

        node = self._node_repository.get_by_id(
            job.assigned_node_id,
            tenant_id,
        )

        if node is None:
            return None

        job.complete()
        node.release(job.resources)

        self._node_repository.save(node)
        self._job_repository.save(job)

        return job
