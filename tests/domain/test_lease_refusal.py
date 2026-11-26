from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.entities.lease import Lease
from app.domain.entities.lease_reclaim import LeaseReclaim
from app.domain.entities.lease_refusal import LeaseRefusal
from app.domain.enums.lease_recovery_path import LeaseRecoveryPath
from app.domain.enums.lease_refusal_operation import LeaseRefusalOperation
from app.domain.enums.lease_refusal_reason import LeaseRefusalReason
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId


def _reclaim() -> LeaseReclaim:
    lease = Lease.create(
        worker_id=WorkerId.new(),
        job_id=JobId.new(),
        tenant_id=TenantId.new(),
        duration=timedelta(seconds=-1),
    )
    return LeaseReclaim.record(
        lease=lease,
        recovered_by=LeaseRecoveryPath.EXPIRED_LEASE,
    )


def _refuse(
    reclaim: LeaseReclaim,
    worker_id: WorkerId | None = None,
    operation: LeaseRefusalOperation = LeaseRefusalOperation.RENEW,
    reason: LeaseRefusalReason = LeaseRefusalReason.NO_ACTIVE_LEASE,
) -> LeaseRefusal:
    return LeaseRefusal.record(
        reclaim=reclaim,
        worker_id=WorkerId.new() if worker_id is None else worker_id,
        operation=operation,
        reason=reason,
    )


def test_the_refusal_takes_tenant_lease_and_job_from_the_reclaim_record() -> None:
    reclaim = _reclaim()

    refusal = _refuse(reclaim)

    assert refusal.tenant_id == reclaim.tenant_id
    assert refusal.lease_id == reclaim.lease_id
    assert refusal.job_id == reclaim.job_id


def test_the_worker_is_the_one_of_the_refused_call() -> None:
    reclaim = _reclaim()
    caller = WorkerId.new()

    refusal = _refuse(reclaim, worker_id=caller)

    assert refusal.worker_id == caller
    assert refusal.worker_id != reclaim.worker_id


@pytest.mark.parametrize("operation", list(LeaseRefusalOperation))
@pytest.mark.parametrize("reason", list(LeaseRefusalReason))
def test_operation_and_reason_are_kept_as_given(
    operation: LeaseRefusalOperation,
    reason: LeaseRefusalReason,
) -> None:
    refusal = _refuse(_reclaim(), operation=operation, reason=reason)

    assert refusal.operation is operation
    assert refusal.reason is reason


def test_refused_at_is_the_time_of_the_call() -> None:
    reclaim = _reclaim()
    before = datetime.now(UTC)

    refusal = _refuse(reclaim)

    assert before <= refusal.refused_at <= datetime.now(UTC)


def test_the_refusal_has_an_id_of_its_own() -> None:
    reclaim = _reclaim()

    first = _refuse(reclaim)
    second = _refuse(reclaim)

    assert first.id != reclaim.lease_id
    assert first.id != reclaim.id
    assert first.id != second.id


def test_a_refusal_is_immutable() -> None:
    refusal = _refuse(_reclaim())

    with pytest.raises(FrozenInstanceError):
        refusal.__setattr__("reason", LeaseRefusalReason.LEASE_NOT_CURRENT)


def test_the_enum_values_are_the_ones_the_table_will_accept() -> None:
    assert {operation.value for operation in LeaseRefusalOperation} == {
        "renew",
        "release",
    }
    assert {reason.value for reason in LeaseRefusalReason} == {
        "no_active_lease",
        "lease_not_current",
    }
