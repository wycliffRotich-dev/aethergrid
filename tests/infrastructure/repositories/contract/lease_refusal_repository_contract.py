from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.domain.entities.lease import Lease
from app.domain.entities.lease_reclaim import LeaseReclaim
from app.domain.entities.lease_refusal import LeaseRefusal
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.enums.lease_recovery_path import LeaseRecoveryPath
from app.domain.enums.lease_refusal_operation import LeaseRefusalOperation
from app.domain.enums.lease_refusal_reason import LeaseRefusalReason
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId

BASE = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


class LeaseRefusalRepositoryContract:
    """
    Shared behavioral contract that every LeaseRefusalRepository
    implementation must satisfy (ADR 0108).
    """

    @pytest.fixture
    def repository(self):
        raise NotImplementedError(
            "Subclasses must provide a `repository` fixture."
        )

    def _reclaim(
        self,
        *,
        tenant_id: TenantId | None = None,
        lease_id: UUID | None = None,
    ) -> LeaseReclaim:
        """
        The record of a reclaimed lease. An implementation whose store
        refuses a refusal for a reclaim or a job that does not exist
        overrides this to persist what the record refers to.
        """
        lease = Lease.create(
            worker_id=WorkerId.new(),
            job_id=JobId.new(),
            tenant_id=DEFAULT_TENANT_ID if tenant_id is None else tenant_id,
            duration=timedelta(seconds=-1),
        )
        if lease_id is not None:
            lease = replace(lease, id=lease_id)
        return LeaseReclaim.record(
            lease=lease,
            recovered_by=LeaseRecoveryPath.EXPIRED_LEASE,
        )

    def _refusal(
        self,
        reclaim: LeaseReclaim,
        *,
        operation: LeaseRefusalOperation = LeaseRefusalOperation.RENEW,
        reason: LeaseRefusalReason = LeaseRefusalReason.NO_ACTIVE_LEASE,
    ) -> LeaseRefusal:
        return LeaseRefusal.record(
            reclaim=reclaim,
            worker_id=WorkerId.new(),
            operation=operation,
            reason=reason,
        )

    @pytest.mark.parametrize("operation", list(LeaseRefusalOperation))
    @pytest.mark.parametrize("reason", list(LeaseRefusalReason))
    def test_save_and_list_round_trips_every_field(
        self,
        repository,
        operation,
        reason,
    ) -> None:
        reclaim = self._reclaim()
        refusal = self._refusal(reclaim, operation=operation, reason=reason)

        repository.save(refusal)

        assert repository.list_for_lease(
            reclaim.lease_id, reclaim.tenant_id
        ) == [refusal]

    def test_list_for_an_unknown_lease_is_empty(self, repository) -> None:
        reclaim = self._reclaim()

        assert repository.list_for_lease(
            reclaim.lease_id, reclaim.tenant_id
        ) == []

    def test_list_in_another_tenant_is_empty(self, repository) -> None:
        reclaim = self._reclaim()
        refusal = self._refusal(reclaim)

        repository.save(refusal)

        assert repository.list_for_lease(reclaim.lease_id, TenantId.new()) == []
        assert repository.list_for_lease(
            reclaim.lease_id, reclaim.tenant_id
        ) == [refusal]

    def test_a_second_refusal_of_the_same_kind_changes_nothing(
        self,
        repository,
    ) -> None:
        reclaim = self._reclaim()
        first = self._refusal(reclaim)
        second = self._refusal(reclaim)

        repository.save(first)
        repository.save(second)

        assert repository.list_for_lease(
            reclaim.lease_id, reclaim.tenant_id
        ) == [first]

    def test_another_operation_is_kept_and_listed_by_time(
        self,
        repository,
    ) -> None:
        reclaim = self._reclaim()
        release = replace(
            self._refusal(reclaim, operation=LeaseRefusalOperation.RELEASE),
            refused_at=BASE + timedelta(seconds=5),
        )
        renew = replace(
            self._refusal(reclaim, operation=LeaseRefusalOperation.RENEW),
            refused_at=BASE,
        )

        repository.save(release)
        repository.save(renew)

        assert repository.list_for_lease(
            reclaim.lease_id, reclaim.tenant_id
        ) == [renew, release]

    def test_another_reason_is_kept(self, repository) -> None:
        reclaim = self._reclaim()
        missing = self._refusal(
            reclaim, reason=LeaseRefusalReason.NO_ACTIVE_LEASE
        )
        other = self._refusal(
            reclaim, reason=LeaseRefusalReason.LEASE_NOT_CURRENT
        )

        repository.save(missing)
        repository.save(other)

        assert len(
            repository.list_for_lease(reclaim.lease_id, reclaim.tenant_id)
        ) == 2

    def test_the_same_lease_id_in_two_tenants_keeps_two_lists(
        self,
        repository,
    ) -> None:
        reclaim_a = self._reclaim()
        reclaim_b = self._reclaim(
            tenant_id=TenantId.new(),
            lease_id=reclaim_a.lease_id,
        )
        refusal_a = self._refusal(reclaim_a)
        refusal_b = self._refusal(
            reclaim_b, operation=LeaseRefusalOperation.RELEASE
        )

        repository.save(refusal_a)
        repository.save(refusal_b)

        assert repository.list_for_lease(
            reclaim_a.lease_id, reclaim_a.tenant_id
        ) == [refusal_a]
        assert repository.list_for_lease(
            reclaim_b.lease_id, reclaim_b.tenant_id
        ) == [refusal_b]

    def test_two_leases_of_one_tenant_keep_a_list_each(
        self,
        repository,
    ) -> None:
        reclaim_one = self._reclaim()
        reclaim_two = self._reclaim()
        refusal_one = self._refusal(reclaim_one)
        refusal_two = self._refusal(reclaim_two)

        repository.save(refusal_one)
        repository.save(refusal_two)

        assert repository.list_for_lease(
            reclaim_one.lease_id, reclaim_one.tenant_id
        ) == [refusal_one]
        assert repository.list_for_lease(
            reclaim_two.lease_id, reclaim_two.tenant_id
        ) == [refusal_two]

    def test_the_same_kind_in_two_tenants_keeps_one_refusal_each(
        self,
        repository,
    ) -> None:
        reclaim_a = self._reclaim()
        reclaim_b = self._reclaim(
            tenant_id=TenantId.new(),
            lease_id=reclaim_a.lease_id,
        )
        refusal_a = self._refusal(reclaim_a)
        refusal_b = self._refusal(reclaim_b)

        repository.save(refusal_a)
        repository.save(refusal_b)

        assert repository.list_for_lease(
            reclaim_a.lease_id, reclaim_a.tenant_id
        ) == [refusal_a]
        assert repository.list_for_lease(
            reclaim_b.lease_id, reclaim_b.tenant_id
        ) == [refusal_b]
