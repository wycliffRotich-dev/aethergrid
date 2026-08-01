from __future__ import annotations

from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.repositories.job_repository import (
    JobRepository,
)
from app.domain.repositories.lease_repository import (
    LeaseRepository,
)
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)


class RecoverExpiredLeaseService:
    """
    Recover work abandoned by expired leases.

    This application service coordinates recovery by
    restoring workers, jobs and leases to a
    consistent state after lease expiration.
    """

    def __init__(
        self,
        worker_repository: WorkerRepository,
        job_repository: JobRepository,
        lease_repository: LeaseRepository,
        record_job_events_service: RecordJobEventsService | None = None,
    ) -> None:
        self._worker_repository = worker_repository
        self._job_repository = job_repository
        self._lease_repository = lease_repository
        self._record_job_events_service = record_job_events_service

    def execute(
        self,
    ) -> None:
        """
        Recover every expired lease.

        Leases that have not yet expired are left untouched;
        their worker is still the legitimate owner of the job.

        A job whose lease expired is reclaimed rather than
        unscheduled: it may be SCHEDULED (worker died before
        starting it) or, far more commonly, RUNNING (worker
        died mid-execution, which is the normal case since a
        lease stays alive for the job's entire runtime).
        reclaim() consumes a retry attempt and fails the job
        outright once retries are exhausted, so a
        consistently unhealthy worker cannot cause a job to
        be reassigned and abandoned forever.
        """
        for lease in self._lease_repository.list():

            if not lease.is_expired():
                continue

            worker = self._worker_repository.get_by_id(
                lease.worker_id,
            )

            job = self._job_repository.get_by_id(
                lease.job_id,
            )

            if worker is not None:
                worker.recover()

                self._worker_repository.save(
                    worker,
                )

            if job is not None:
                job.reclaim()

                self._job_repository.save(
                    job,
                )

                if self._record_job_events_service is not None:
                    self._record_job_events_service.record(
                        aggregate_id=str(job.id),
                        event_type="JobReclaimed",
                    )

            self._lease_repository.delete(
                lease.job_id,
            )
