from __future__ import annotations

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

        # worker.start() mutates worker.running_job (the same
        # Job object) to RUNNING in memory, but never persists
        # that job on its own -- WorkerRepository.save() only
        # writes the workers table. Without this, the jobs
        # table row stays SCHEDULED forever for any backend
        # that reconstructs Job independently of Worker (real
        # Postgres/SQLite, not the in-memory repositories that
        # happen to share object references and mask this).
        # Discovered running a real standalone agent against
        # real Postgres for the first time (ADR 0019, ADR 0030
        # fleet-scale testing) -- every prior job completion
        # went through WorkerExecutionLoop's in-process path
        # instead, which never hits this gap.
        if worker.running_job is not None:
            self._job_repository.save(
                worker.running_job,
            )

        return worker
