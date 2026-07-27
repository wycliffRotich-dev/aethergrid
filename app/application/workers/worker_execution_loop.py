from __future__ import annotations

from app.application.services.job_execution_service import (
    JobExecutionService,
)
from app.application.services.release_lease_service import (
    ReleaseLeaseService,
)
from app.application.services.renew_lease_service import (
    RenewLeaseService,
)
from app.domain.repositories.job_repository import (
    JobRepository,
)
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)
from app.domain.value_objects.worker_id import (
    WorkerId,
)


class WorkerExecutionLoop:
    """
    Executes one worker iteration.

    A worker renews its lease, actually executes its
    assigned job as a real subprocess, records the real
    outcome (success, failure, or timeout) on both the job
    and the worker, and finally releases the lease
    regardless of that outcome.

    Lease release is unconditional: a lease must never be
    left dangling just because the job it was protecting
    failed. Job outcome and lease lifecycle are deliberately
    kept as two separate concerns, decided here and merely
    executed by the collaborators below.

    The job reference is captured before calling
    worker.complete()/worker.fail(), since both clear
    worker.running_job as part of their own transition.
    Saving that captured reference afterward is what
    persists the job's final state and exit code.
    """

    def __init__(
        self,
        worker_repository: WorkerRepository,
        job_repository: JobRepository,
        renew_lease_service: RenewLeaseService,
        release_lease_service: ReleaseLeaseService,
        job_execution_service: JobExecutionService,
    ) -> None:
        self._worker_repository = worker_repository
        self._job_repository = job_repository
        self._renew_lease_service = renew_lease_service
        self._release_lease_service = release_lease_service
        self._job_execution_service = job_execution_service

    def execute(
        self,
        worker_id: WorkerId,
    ) -> None:
        """
        Execute one worker iteration.
        """
        worker = self._worker_repository.get_by_id(
            worker_id,
        )

        if worker is None:
            raise ValueError(
                "Worker does not exist."
            )

        if worker.running_job is None:
            return

        job = worker.running_job

        # Skip if job is already running or in a terminal state
        if job.is_running() or job.is_completed() or job.is_failed() or job.is_cancelled():
            return

        self._renew_lease_service.execute(
            worker_id,
        )

        worker.start()

        result = self._job_execution_service.execute(
            command=job.command,
            timeout=job.execution_timeout,
        )

        if result.succeeded:
            worker.complete(
                exit_code=result.exit_code,
            )
        else:
            worker.fail(
                exit_code=result.exit_code,
            )

        self._job_repository.save(
            job,
        )

        self._worker_repository.save(
            worker,
        )

        self._release_lease_service.execute(
            worker_id,
        )
