from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from app.domain.entities.lease import Lease
from app.domain.exceptions.lease_not_found_error import LeaseNotFoundError
from app.domain.repositories.lease_repository import (
    LeaseRepository,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId


class InMemoryLeaseRepository(
    LeaseRepository,
):
    """
    In-memory implementation of the LeaseRepository.
    """

    def __init__(
        self,
    ) -> None:
        self._leases: dict[str, Lease] = {}

    def save(
        self,
        lease: Lease,
    ) -> None:
        self._leases[
            str(lease.job_id)
        ] = lease

    def renew(
        self,
        lease_id: UUID,
        duration: timedelta,
        tenant_id: TenantId,
    ) -> None:
        # dict is keyed by job_id, not lease id, so this is a scan --
        # fine at test-suite scale, and it keeps the lookup shape
        # identical to what the Postgres WHERE id = ... does
        for lease in self._leases.values():
            if lease.id == lease_id and lease.tenant_id == tenant_id:
                lease.renew(duration)
                return

        raise LeaseNotFoundError(lease_id)

    def get_by_job_id(
        self,
        job_id: JobId,
        tenant_id: TenantId,
    ) -> Lease | None:
        lease = self._leases.get(
            str(job_id),
        )

        if lease is None or lease.tenant_id != tenant_id:
            return None

        return lease

    def get_by_worker_id(
        self,
        worker_id: WorkerId,
        tenant_id: TenantId,
    ) -> Lease | None:
        for lease in self._leases.values():
            if lease.worker_id == worker_id and lease.tenant_id == tenant_id:
                return lease

        return None

    def list_across_tenants(
        self,
    ) -> list[Lease]:
        return list(
            self._leases.values(),
        )

    def delete(
        self,
        job_id: JobId,
        tenant_id: TenantId,
    ) -> None:
        lease = self._leases.get(str(job_id))

        if lease is not None and lease.tenant_id == tenant_id:
            del self._leases[str(job_id)]

    def delete_if_expired(
        self,
        job_id: JobId,
        tenant_id: TenantId,
    ) -> bool:
        lease = self._leases.get(str(job_id))

        if (
            lease is None
            or lease.tenant_id != tenant_id
            or not lease.is_expired()
        ):
            return False

        del self._leases[str(job_id)]

        return True

