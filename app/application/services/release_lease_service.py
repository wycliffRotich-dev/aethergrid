from __future__ import annotations

from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.repositories.lease_repository import (
    LeaseRepository,
)
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)
from app.domain.value_objects.worker_id import WorkerId


class ReleaseLeaseService:
    """
    Release the active lease owned by a worker.

    This service is purely about lease bookkeeping. It does
    not decide whether the job the lease was protecting
    succeeded or failed -- that decision is made by whoever
    actually ran the job (WorkerExecutionLoop), before the
    lease is released. A lease must always be released once
    a worker is done with a job, regardless of that job's
    outcome.
    """

    def __init__(
        self,
        lease_repository: LeaseRepository,
        worker_repository: WorkerRepository,
        record_job_events_service: RecordJobEventsService | None = None,
    ) -> None:
        self._lease_repository = lease_repository
        self._worker_repository = worker_repository
        self._record_job_events_service = record_job_events_service

    def execute(
        self,
        worker_id: WorkerId,
    ) -> None:
        lease = self._lease_repository.get_by_worker_id(
            worker_id,
        )

        if lease is None:
            raise ValueError(
                "Worker does not own an active lease."
            )

        worker = self._worker_repository.get_by_id(
            worker_id,
        )

        if worker is None:
            raise ValueError(
                "Worker does not exist."
            )

        self._lease_repository.delete(
            lease.job_id,
        )

        if self._record_job_events_service is not None:
            self._record_job_events_service.record(
                aggregate_id=str(lease.job_id),
                event_type="LeaseReleased",
            )
