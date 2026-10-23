from __future__ import annotations

from uuid import UUID

from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.exceptions.job_not_found_error import (
    JobNotFoundError,
)
from app.domain.exceptions.lease_not_found_error import (
    LeaseNotFoundError,
)
from app.domain.exceptions.no_active_lease_error import (
    NoActiveLeaseError,
)
from app.domain.exceptions.worker_not_found_error import (
    WorkerNotFoundError,
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
from app.domain.value_objects.tenant_id import TenantId
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

    expected_lease_id (ADR 0034) fences this call against a
    real, previously-unguarded race: without it, this method
    looked up whatever lease a worker currently holds by
    worker_id alone and deleted it unconditionally. A caller
    whose own lease was already reclaimed by reconciliation,
    with the same worker later legitimately reacquired for a
    different job, would silently delete that new, unrelated
    lease instead, stealing ownership out from under a
    currently-legitimate execution. Requiring the caller to
    state which lease it believes it is releasing, and
    verifying that identity before deleting anything, closes
    that gap the same way renew() already refuses to
    resurrect a lease that no longer matches.
    """

    def __init__(
        self,
        lease_repository: LeaseRepository,
        worker_repository: WorkerRepository,
        record_job_events_service: RecordJobEventsService | None = None,
        job_repository: JobRepository | None = None,
    ) -> None:
        # An event takes its tenant from its job (ADR 0074), and the
        # lease holds only the job id. Recording therefore needs a
        # job repository, and this refuses the pair that cannot work.
        if record_job_events_service is not None and job_repository is None:
            raise ValueError(
                "record_job_events_service needs a job_repository"
            )

        self._lease_repository = lease_repository
        self._worker_repository = worker_repository
        self._record_job_events_service = record_job_events_service
        self._job_repository = job_repository

    def execute(
        self,
        worker_id: WorkerId,
        expected_lease_id: UUID,
        tenant_id: TenantId,
    ) -> None:
        lease = self._lease_repository.get_by_worker_id(
            worker_id,
            tenant_id,
        )

        if lease is None:
            raise NoActiveLeaseError(worker_id)

        if lease.id != expected_lease_id:
            # Whatever lease is on record for this worker is
            # not the one the caller started with. Either
            # reconciliation already reclaimed the original
            # (and the worker may or may not have been
            # legitimately reassigned since), or the caller is
            # simply wrong about what it holds. Either way,
            # deleting it would remove a lease this caller has
            # no claim to. Raised the same way renew() already
            # refuses to resurrect a reclaimed lease.
            raise LeaseNotFoundError(expected_lease_id)

        worker = self._worker_repository.get_by_id(
            worker_id,
            tenant_id,
        )

        if worker is None:
            raise WorkerNotFoundError(worker_id)

        job = None

        if self._record_job_events_service is not None:
            # The lookup comes before the delete, so a missing job
            # leaves the lease in place. The lease was read in this
            # tenant, so its job is read in this tenant too. A job in
            # another tenant reads as missing.
            job = self._job_repository.get_by_id(
                lease.job_id,
                tenant_id,
            )

            if job is None:
                raise JobNotFoundError(lease.job_id)

        self._lease_repository.delete(
            lease.job_id,
            tenant_id,
        )

        if job is not None:
            self._record_job_events_service.record_for_job(
                job,
                event_type="LeaseReleased",
            )
