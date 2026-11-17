from __future__ import annotations

import copy

from app.domain.entities.job import Job
from app.domain.exceptions.job_status_conflict_error import (
    JobStatusConflictError,
)
from app.domain.repositories.job_repository import JobRepository
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId

_MAX_STATUS_RETRIES = 8


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

    Every write is fenced by the lifecycle snapshot that was
    read (ADR 0106). Transitions are applied to a copy so a
    refused write never mutates an in-memory instance shared
    with another caller, and when a concurrent writer changes
    the job between get_by_id and save_if_unchanged the
    service re-reads the job to decide against its new state.
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
        Cancel a job, or request cancellation of a running
        one.

        Returns:
            The job in its resulting state if found in the
            tenant, otherwise None.
        """
        for _ in range(_MAX_STATUS_RETRIES):
            current = self._job_repository.get_by_id(
                job_id,
                tenant_id,
            )

            if current is None:
                return None

            expected = copy.deepcopy(current)

            if expected.is_cancelling():
                return expected

            candidate = copy.deepcopy(expected)

            if candidate.is_running():
                candidate.request_cancellation()
            else:
                candidate.cancel()

            if self._job_repository.save_if_unchanged(
                candidate,
                expected,
            ):
                return candidate

        raise JobStatusConflictError(
            f"Could not settle cancellation of job {job_id} after "
            f"{_MAX_STATUS_RETRIES} concurrent state changes."
        )
