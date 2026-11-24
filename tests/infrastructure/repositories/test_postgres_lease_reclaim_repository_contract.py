from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from app.domain.entities.lease import Lease
from app.domain.entities.lease_reclaim import LeaseReclaim
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.enums.lease_recovery_path import LeaseRecoveryPath
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.postgres_job_repository import (
    PostgresJobRepository,
)
from app.infrastructure.repositories.postgres_lease_reclaim_repository import (
    PostgresLeaseReclaimRepository,
)
from tests.infrastructure.repositories.contract.lease_reclaim_repository_contract import (
    LeaseReclaimRepositoryContract,
)
from tests.support.jobs import make_job


@pytest.fixture(scope="session")
def pool(test_database_url):
    test_pool = ConnectionPool(
        test_database_url,
        min_size=1,
        max_size=5,
        open=True,
        kwargs={"autocommit": True},
    )
    yield test_pool
    test_pool.close()


class TestPostgresLeaseReclaimRepositoryContract(
    LeaseReclaimRepositoryContract,
):
    """
    The postgres lease_reclaims table refuses a record whose job is
    missing or is in another tenant, and whose tenant does not exist. The
    base contract builds leases that point at nothing, so here _lease
    persists the tenant and the job the lease refers to, as the lease
    contract does for its worker and job.
    """

    @pytest.fixture
    def repository(self, pool):
        self._pool = pool
        self._created_tenants: list[UUID] = []

        with pool.connection() as conn:
            conn.execute("TRUNCATE lease_reclaims, jobs CASCADE")

        yield PostgresLeaseReclaimRepository(pool)

        with pool.connection() as conn:
            conn.execute("TRUNCATE lease_reclaims, jobs CASCADE")

            if self._created_tenants:
                conn.execute(
                    "DELETE FROM tenants WHERE id = ANY(%s)",
                    (self._created_tenants,),
                )

    def _lease(self, *, tenant_id: TenantId | None = None) -> Lease:
        lease = super()._lease(tenant_id=tenant_id)

        if lease.tenant_id != DEFAULT_TENANT_ID:
            with self._pool.connection() as conn:
                conn.execute(
                    "INSERT INTO tenants (id, name, created_at) "
                    "VALUES (%s, %s, now())",
                    (lease.tenant_id.value, f"tenant-{lease.tenant_id}"),
                )

            self._created_tenants.append(lease.tenant_id.value)

        PostgresJobRepository(self._pool).save(
            make_job(id=lease.job_id, tenant_id=lease.tenant_id),
        )

        return lease

    def test_a_record_for_a_job_that_does_not_exist_is_refused(
        self,
        repository,
    ) -> None:
        lease = LeaseReclaimRepositoryContract._lease(self)
        record = LeaseReclaim.record(
            lease=lease,
            recovered_by=LeaseRecoveryPath.EXPIRED_LEASE,
        )

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            repository.save(record)

        assert repository.get_by_lease_id(lease.id, lease.tenant_id) is None

    def test_a_record_for_a_job_in_another_tenant_is_refused(
        self,
        repository,
    ) -> None:
        lease_of_b = self._lease(tenant_id=TenantId.new())
        record = LeaseReclaim.record(
            lease=replace(lease_of_b, tenant_id=DEFAULT_TENANT_ID),
            recovered_by=LeaseRecoveryPath.EXPIRED_LEASE,
        )

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            repository.save(record)

        assert repository.get_by_lease_id(lease_of_b.id, DEFAULT_TENANT_ID) is None
        assert repository.get_by_lease_id(lease_of_b.id, lease_of_b.tenant_id) is None
