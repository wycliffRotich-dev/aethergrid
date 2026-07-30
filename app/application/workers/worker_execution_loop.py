from __future__ import annotations

import threading

from app.application.services.job_execution_service import (
    JobExecutionService,
)
from app.application.services.release_lease_service import (
    ReleaseLeaseService,
)
from app.application.services.renew_lease_service import (
    RenewLeaseService,
)
from app.domain.entities.lease import DEFAULT_LEASE_DURATION
from app.domain.exceptions.lease_not_found_error import LeaseNotFoundError
from app.domain.repositories.job_repository import (
    JobRepository,
)
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)
from app.domain.value_objects.worker_id import (
    WorkerId,
)

# renew at roughly a third of the lease duration -- gives two missed
# heartbeats worth of margin before the lease actually lapses
RENEWAL_INTERVAL_SECONDS = DEFAULT_LEASE_DURATION.total_seconds() / 3


class WorkerExecutionLoop:
    """
    Executes one worker iteration.

    A worker renews its lease, actually executes its assigned
    job as a real subprocess, records the real outcome
    (success, failure, or timeout) on both the job and the
    worker, and finally releases the lease regardless of that
    outcome.

    Job execution can run far longer than a single lease
    period, so renewal can't just happen once up front --
    it has to keep happening in the background for the life of
    the subprocess. If a renewal ever comes back with
    LeaseNotFoundError, that means reconciliation already
    reclaimed this job out from under us, and whatever the
    subprocess eventually returns must not get persisted --
    someone else may already own it.

    The job reference is captured before calling
    worker.complete()/worker.fail(), since both clear
    worker.running_job as part of their own transition.
    Saving that captured reference afterward is what persists
    the job's final state and exit code.
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

        worker.start()

        stop_renewing = threading.Event()
        lost_lease: list[LeaseNotFoundError] = []

        def keep_lease_alive() -> None:
            # wait() returns True once stop_renewing is set (we're
            # done executing), False on each timeout -- that's our
            # actual renew signal
            while not stop_renewing.wait(RENEWAL_INTERVAL_SECONDS):
                try:
                    self._renew_lease_service.execute(worker_id)
                except LeaseNotFoundError as exc:
                    lost_lease.append(exc)
                    return

        renewal_thread = threading.Thread(
            target=keep_lease_alive,
            daemon=True,
        )
        renewal_thread.start()

        try:
            result = self._job_execution_service.execute(
                command=job.command,
                timeout=job.execution_timeout,
            )
        finally:
            stop_renewing.set()
            renewal_thread.join()

        if lost_lease:
            # the subprocess result is real, but we've lost the right
            # to record it as canonical -- drop it on the floor rather
            # than risk stomping whoever reconciliation handed this to
            raise lost_lease[0]

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
