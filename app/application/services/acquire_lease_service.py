from __future__ import annotations

from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.worker import Worker
from app.domain.repositories.lease_repository import LeaseRepository


class AcquireLeaseService:
    """
    Creates a lease when a worker starts executing a job.
    """

    def __init__(
        self,
        lease_repository: LeaseRepository,
        record_job_events_service: RecordJobEventsService | None = None,
    ) -> None:
        self._lease_repository = lease_repository
        self._record_job_events_service = record_job_events_service

    def execute(
        self,
        worker: Worker,
        job: Job,
    ) -> Lease:
        """
        Acquire exclusive ownership of a job
        for a worker.
        """

        existing = self._lease_repository.get_by_job_id(
            job.id,
        )

        if existing is not None:
            raise ValueError(
                "Job already has an active lease."
            )

        lease = Lease.create(
            worker_id=worker.id,
            job_id=job.id,
        )

        self._lease_repository.save(
            lease,
        )

        if self._record_job_events_service is not None:
            self._record_job_events_service.record(
                aggregate_id=str(job.id),
                event_type="LeaseAcquired",
            )

        return lease
