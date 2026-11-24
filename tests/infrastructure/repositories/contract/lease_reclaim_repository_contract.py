from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.entities.lease import Lease
from app.domain.entities.lease_reclaim import LeaseReclaim
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.enums.lease_recovery_path import LeaseRecoveryPath
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId


class LeaseReclaimRepositoryContract:
    """
    Shared behavioral contract that every LeaseReclaimRepository
    implementation must satisfy (ADR 0107).
    """

    @pytest.fixture
    def repository(self):
        raise NotImplementedError(
            "Subclasses must provide a `repository` fixture."
        )

    def _lease(self, *, tenant_id: TenantId | None = None) -> Lease:
        """
        An expired lease. An implementation whose store refuses a record
        for a job that does not exist overrides this to persist what the
        lease refers to.
        """
        return Lease.create(
            worker_id=WorkerId.new(),
            job_id=JobId.new(),
            tenant_id=DEFAULT_TENANT_ID if tenant_id is None else tenant_id,
            duration=timedelta(seconds=-1),
        )

    @pytest.mark.parametrize("path", list(LeaseRecoveryPath))
    def test_save_and_get_by_lease_id_round_trips_every_field(
        self,
        repository,
        path,
    ) -> None:
        lease = self._lease()
        record = LeaseReclaim.record(lease=lease, recovered_by=path)

        repository.save(record)

        assert repository.get_by_lease_id(lease.id, lease.tenant_id) == record

    def test_get_by_lease_id_returns_none_for_an_unknown_lease(
        self,
        repository,
    ) -> None:
        lease = self._lease()

        assert repository.get_by_lease_id(lease.id, lease.tenant_id) is None

    def test_get_by_lease_id_in_another_tenant_returns_none(
        self,
        repository,
    ) -> None:
        lease = self._lease()
        record = LeaseReclaim.record(
            lease=lease,
            recovered_by=LeaseRecoveryPath.EXPIRED_LEASE,
        )

        repository.save(record)

        assert repository.get_by_lease_id(lease.id, TenantId.new()) is None
        assert repository.get_by_lease_id(lease.id, lease.tenant_id) == record

    def test_a_second_record_for_the_same_lease_changes_nothing(
        self,
        repository,
    ) -> None:
        lease = self._lease()
        first = LeaseReclaim.record(
            lease=lease,
            recovered_by=LeaseRecoveryPath.EXPIRED_LEASE,
        )
        second = LeaseReclaim.record(
            lease=lease,
            recovered_by=LeaseRecoveryPath.OFFLINE_NODE,
        )

        repository.save(first)
        repository.save(second)

        assert repository.get_by_lease_id(lease.id, lease.tenant_id) == first

    def test_the_same_lease_id_in_two_tenants_keeps_two_records(
        self,
        repository,
    ) -> None:
        lease_a = self._lease()
        lease_b = replace(
            self._lease(tenant_id=TenantId.new()),
            id=lease_a.id,
        )
        record_a = LeaseReclaim.record(
            lease=lease_a,
            recovered_by=LeaseRecoveryPath.EXPIRED_LEASE,
        )
        record_b = LeaseReclaim.record(
            lease=lease_b,
            recovered_by=LeaseRecoveryPath.OFFLINE_NODE,
        )

        repository.save(record_a)
        repository.save(record_b)

        assert repository.get_by_lease_id(lease_a.id, lease_a.tenant_id) == record_a
        assert repository.get_by_lease_id(lease_b.id, lease_b.tenant_id) == record_b
