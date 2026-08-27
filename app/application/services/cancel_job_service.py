from __future__ import annotations

from app.domain.entities.job import Job
from app.domain.repositories.job_repository import JobRepository
from app.domain.value_objects.job_id import JobId


class CancelJobService:
    """
    Application service responsible for cancelling a job.

    Queued or scheduled jobs are cancelled immediately, no
    subprocess is running yet for them to interrupt. A
    running job instead has its cancellation requested (ADR
    0029): it moves to CANCELLING, and actual termination is
    delivered asynchronously to the worker on its next lease
    renewal, not by this service directly. A job already
    CANCELLING is treated as an idempotent no-op rather than
    forced straight to CANCELLED, since that would mark it
    cancelled before the subprocess is actually confirmed
    dead.
    """

    def __init__(
        self,
        job_repository: JobRepository,
    ) -> None:
        self._job_repository = job_repository

    def execute(
        self,
        job_id: JobId,
    ) -> Job | None:
        """
        Cancel a job, or request cancellation of a running
        one.

        Returns:
            The job in its resulting state if found,
            otherwise None.
        """
        job = self._job_repository.get_by_id(
            job_id,
        )

        if job is None:
            return None

        if job.is_running():
            job.request_cancellation()
        elif not job.is_cancelling():
            job.cancel()

        self._job_repository.save(
            job,
        )

        return job
