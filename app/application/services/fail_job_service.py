from __future__ import annotations

from app.domain.entities.job import Job
from app.domain.repositories.job_repository import JobRepository
from app.domain.repositories.node_repository import (
    NodeRepository,
)
from app.domain.value_objects.job_id import JobId


class FailJobService:
    """
    Application service responsible for failing a job
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
    ) -> Job | None:
        """
        Fail a running job.

        Returns:
            The failed job if found, otherwise None.
        """
        job = self._job_repository.get_by_id(
            job_id,
        )

        if job is None:
            return None

        if job.assigned_node_id is None:
            return None

        node = self._node_repository.get_by_id(
            job.assigned_node_id,
        )

        if node is None:
            return None

        job.fail()

        node.release(
            job.resources,
        )

        self._node_repository.save(
            node,
        )
        self._job_repository.save(
            job,
        )

        return job
