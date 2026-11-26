from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from app.domain.entities.lease_reclaim import LeaseReclaim
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.postgres_job_repository import (
    PostgresJobRepository,
)
from app.infrastructure.repositories.postgres_lease_reclaim_repository import (
    PostgresLeaseReclaimRepository,
)
from app.infrastructure.repositories.postgres_lease_refusal_repository import (
    PostgresLeaseRefusalRepository,
)
from tests.infrastructure.repositories.contract.lease_refusal_repository_contract import (
    LeaseRefusalRepositoryContract,
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


class TestPostgresLeaseRefusalRepositoryContract(
    LeaseRefusalRepositoryContract,
):
    """
    The postgres lease_refusals table refuses a record whose reclaim
    record is missing, in another tenant, or whose job is missing. The
    base contract builds reclaim records that point at nothing, so here
    _reclaim persists the tenant, the job and the reclaim record that the
    refusal refers to.
    """

    @pytest.fixture
    def repository(self, pool):
        self._pool = pool
        self._created_tenants: list[UUID] = []

        with pool.connection() as conn:
            conn.execute(
                "TRUNCATE lease_refusals, lease_reclaims, jobs CASCADE"
            )

        yield PostgresLeaseRefusalRepository(pool)

        with pool.connection() as conn:
            conn.execute(
                "TRUNCATE lease_refusals, lease_reclaims, jobs CASCADE"
            )

            if self._created_tenants:
                conn.execute(
                    "DELETE FROM tenants WHERE id = ANY(%s)",
                    (self._created_tenants,),
                )

    def _reclaim(
        self,
        *,
        tenant_id: TenantId | None = None,
        lease_id: UUID | None = None,
    ) -> LeaseReclaim:
        reclaim = super()._reclaim(tenant_id=tenant_id, lease_id=lease_id)

        if reclaim.tenant_id != DEFAULT_TENANT_ID:
            with self._pool.connection() as conn:
                conn.execute(
                    "INSERT INTO tenants (id, name, created_at) "
                    "VALUES (%s, %s, now())",
                    (reclaim.tenant_id.value, f"tenant-{reclaim.tenant_id}"),
                )

            self._created_tenants.append(reclaim.tenant_id.value)

        PostgresJobRepository(self._pool).save(
            make_job(id=reclaim.job_id, tenant_id=reclaim.tenant_id),
        )
        PostgresLeaseReclaimRepository(self._pool).save(reclaim)

        return reclaim

    def test_a_refusal_for_a_lease_that_reclaim_never_removed_is_refused(
        self,
        repository,
    ) -> None:
        reclaim = LeaseRefusalRepositoryContract._reclaim(self)
        PostgresJobRepository(self._pool).save(
            make_job(id=reclaim.job_id, tenant_id=reclaim.tenant_id),
        )
        refusal = self._refusal(reclaim)

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            repository.save(refusal)

        assert repository.list_for_lease(
            reclaim.lease_id, reclaim.tenant_id
        ) == []

    def test_a_refusal_in_another_tenant_than_its_reclaim_is_refused(
        self,
        repository,
    ) -> None:
        reclaim_of_b = self._reclaim(tenant_id=TenantId.new())
        refusal = replace(
            self._refusal(reclaim_of_b),
            tenant_id=DEFAULT_TENANT_ID,
        )

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            repository.save(refusal)

        assert repository.list_for_lease(
            reclaim_of_b.lease_id, DEFAULT_TENANT_ID
        ) == []
        assert repository.list_for_lease(
            reclaim_of_b.lease_id, reclaim_of_b.tenant_id
        ) == []
