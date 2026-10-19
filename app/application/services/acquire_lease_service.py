from __future__ import annotations

from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.worker import Worker
from app.domain.exceptions.lease_tenant_mismatch_error import (
    LeaseTenantMismatchError,
)
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

        The lease takes the tenant of its worker. A job in another
        tenant gets no lease and nothing is recorded (ADR 0075).
        The scheduler never pairs a job with a node of another
        tenant (ADR 0064 point 6), so this guards against a mistake
        and is not expected to fire.
        """
        if job.tenant_id != worker.tenant_id:
            raise LeaseTenantMismatchError(
                "Worker and job belong to different tenants."
            )

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
            tenant_id=worker.tenant_id,
        )

        self._lease_repository.save(
            lease,
        )

        if self._record_job_events_service is not None:
            self._record_job_events_service.record_for_job(
                job,
                event_type="LeaseAcquired",
            )

        return lease
