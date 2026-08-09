from __future__ import annotations

from app.domain.entities.job import Job
from app.domain.enums.job_status import JobStatus
from app.domain.repositories.job_repository import JobRepository
from app.domain.value_objects.job_id import JobId


class InMemoryJobRepository(JobRepository):
    """
    In-memory implementation of the JobRepository.
    """

    def __init__(
        self,
        jobs: list[Job] | None = None,
    ) -> None:
        self._jobs: dict[str, Job] = {}

        if jobs is not None:
            for job in jobs:
                self.save(job)

    def save(
        self,
        job: Job,
    ) -> None:
        self._jobs[str(job.id)] = job

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
    ) -> Job | None:
        return self._jobs.get(str(job_id))

    def list(
        self,
    ) -> list[Job]:
        return list(self._jobs.values())

    def list_queued(
        self,
    ) -> list[Job]:
        """
        Return all queued jobs.
        """
        return [
            job
            for job in self._jobs.values()
            if job.status == JobStatus.QUEUED
        ]

    def list_recent(
        self,
        limit: int,
    ) -> list[Job]:
        """
        Return the most recently submitted jobs, newest
        first, capped at `limit`.
        """
        return sorted(
            self._jobs.values(),
            key=lambda job: job.submitted_at,
            reverse=True,
        )[:limit]
