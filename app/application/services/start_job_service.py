from __future__ import annotations

from app.application.services.job_execution_support import (
    persist_job_started,
)
from app.domain.entities.worker import Worker
from app.domain.exceptions.worker_job_mismatch_error import (
    WorkerJobMismatchError,
)
from app.domain.exceptions.worker_not_found_error import (
    WorkerNotFoundError,
)
from app.domain.repositories.job_repository import JobRepository
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.worker_id import WorkerId


class StartJobService:
    """
    Application service responsible for confirming that a
    worker has actually begun executing the job assigned to
    it.

    Assignment (AssignWorkerService) only attaches a job to a
    worker; the job stays SCHEDULED until whatever is actually
    executing it, today the same process, eventually a real
    agent (ADR 0019), calls this to confirm execution has
    genuinely started. This is the transition that makes
    RUNNING mean what it says.
    """

    def __init__(
        self,
        worker_repository: WorkerRepository,
        job_repository: JobRepository,
    ) -> None:
        self._worker_repository = worker_repository
        self._job_repository = job_repository

    def execute(
        self,
        worker_id: WorkerId,
        job_id: JobId,
    ) -> Worker:
        """
        Transition the worker's currently held job to RUNNING.

        Raises:
            WorkerNotFoundError: the worker does not exist.
            WorkerJobMismatchError: the worker exists but does
                not currently hold job_id as its running_job.
        """
        worker = self._worker_repository.get_by_id(
            worker_id,
        )

        if worker is None:
            raise WorkerNotFoundError(worker_id)

        if (
            worker.running_job is None
            or worker.running_job.id != job_id
        ):
            raise WorkerJobMismatchError(
                f"Worker '{worker_id}' does not currently "
                f"hold job '{job_id}'."
            )

        worker.start()

        self._worker_repository.save(
            worker,
        )

        # Discovered running a real standalone agent against
        # real Postgres for the first time (ADR 0019, ADR 0030
        # fleet-scale testing): WorkerRepository.save() only
        # writes the workers table, never the job. See
        # persist_job_started's docstring and ADR 0033 for the
        # full reasoning; this same fix is now shared with
        # WorkerExecutionLoop rather than duplicated.
        persist_job_started(
            self._job_repository,
            worker,
        )

        return worker
