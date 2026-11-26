from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from app.application.services.record_lease_refusal_service import (
    RecordLeaseRefusalService,
)
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
from app.infrastructure.repositories.in_memory_lease_reclaim_repository import (
    InMemoryLeaseReclaimRepository,
)
from app.infrastructure.repositories.in_memory_lease_refusal_repository import (
    InMemoryLeaseRefusalRepository,
)


class _SpyRefusals(InMemoryLeaseRefusalRepository):
    def __init__(self) -> None:
        super().__init__()
        self.saved: list[LeaseRefusal] = []

    def save(self, refusal: LeaseRefusal) -> None:
        self.saved.append(refusal)
        super().save(refusal)


class _FailingRefusals(InMemoryLeaseRefusalRepository):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    def save(self, refusal: LeaseRefusal) -> None:
        raise self._error


class _FailingReclaims(InMemoryLeaseReclaimRepository):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    def get_by_lease_id(self, lease_id, tenant_id):
        raise self._error


def _reclaim(tenant_id: TenantId = DEFAULT_TENANT_ID) -> LeaseReclaim:
    lease = Lease.create(
        worker_id=WorkerId.new(),
        job_id=JobId.new(),
        tenant_id=tenant_id,
        duration=timedelta(seconds=-1),
    )
    return LeaseReclaim.record(
        lease=lease,
        recovered_by=LeaseRecoveryPath.EXPIRED_LEASE,
    )


def _service(reclaims, refusals) -> RecordLeaseRefusalService:
    return RecordLeaseRefusalService(
        lease_reclaim_repository=reclaims,
        lease_refusal_repository=refusals,
    )


def _record(service, reclaim, worker_id=None, operation=None, reason=None):
    service.record(
        lease_id=reclaim.lease_id,
        tenant_id=reclaim.tenant_id,
        worker_id=WorkerId.new() if worker_id is None else worker_id,
        operation=(
            LeaseRefusalOperation.RENEW if operation is None else operation
        ),
        reason=(
            LeaseRefusalReason.NO_ACTIVE_LEASE if reason is None else reason
        ),
    )


def test_a_refusal_of_a_reclaimed_lease_is_saved_with_the_values_of_the_call() -> None:
    reclaims = InMemoryLeaseReclaimRepository()
    refusals = InMemoryLeaseRefusalRepository()
    reclaim = _reclaim()
    reclaims.save(reclaim)
    worker_id = WorkerId.new()

    _record(_service(reclaims, refusals), reclaim, worker_id=worker_id)

    saved = refusals.list_for_lease(reclaim.lease_id, reclaim.tenant_id)

    assert len(saved) == 1
    refusal = saved[0]
    assert refusal.lease_id == reclaim.lease_id
    assert refusal.id != reclaim.lease_id
    assert refusal.tenant_id == reclaim.tenant_id
    assert refusal.job_id == reclaim.job_id
    assert refusal.worker_id == worker_id
    assert refusal.worker_id != reclaim.worker_id


@pytest.mark.parametrize("operation", list(LeaseRefusalOperation))
@pytest.mark.parametrize("reason", list(LeaseRefusalReason))
def test_operation_and_reason_are_stored_as_given(operation, reason) -> None:
    reclaims = InMemoryLeaseReclaimRepository()
    refusals = InMemoryLeaseRefusalRepository()
    reclaim = _reclaim()
    reclaims.save(reclaim)

    _record(
        _service(reclaims, refusals),
        reclaim,
        operation=operation,
        reason=reason,
    )

    saved = refusals.list_for_lease(reclaim.lease_id, reclaim.tenant_id)

    assert len(saved) == 1
    assert saved[0].operation is operation
    assert saved[0].reason is reason


def test_a_lease_without_a_reclaim_record_records_nothing() -> None:
    refusals = _SpyRefusals()
    reclaim = _reclaim()

    _record(
        _service(InMemoryLeaseReclaimRepository(), refusals),
        reclaim,
    )

    assert refusals.saved == []


def test_a_reclaim_record_in_another_tenant_records_nothing() -> None:
    reclaims = InMemoryLeaseReclaimRepository()
    refusals = _SpyRefusals()
    reclaim = _reclaim()
    reclaims.save(reclaim)
    other_tenant = TenantId.new()

    _service(reclaims, refusals).record(
        lease_id=reclaim.lease_id,
        tenant_id=other_tenant,
        worker_id=WorkerId.new(),
        operation=LeaseRefusalOperation.RENEW,
        reason=LeaseRefusalReason.NO_ACTIVE_LEASE,
    )

    assert refusals.saved == []


def test_one_call_saves_exactly_one_refusal() -> None:
    reclaims = InMemoryLeaseReclaimRepository()
    refusals = _SpyRefusals()
    reclaim = _reclaim()
    reclaims.save(reclaim)

    _record(_service(reclaims, refusals), reclaim)

    assert len(refusals.saved) == 1


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError, OSError])
def test_a_failed_read_does_not_raise(error_type: type[Exception]) -> None:
    service = _service(
        _FailingReclaims(error_type("database down")),
        InMemoryLeaseRefusalRepository(),
    )

    _record(service, _reclaim())


def test_a_failed_read_saves_nothing() -> None:
    refusals = _SpyRefusals()
    service = _service(_FailingReclaims(RuntimeError("database down")), refusals)

    _record(service, _reclaim())

    assert refusals.saved == []


def test_a_failed_read_logs_one_warning_with_the_lease_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = _service(
        _FailingReclaims(RuntimeError("database down")),
        InMemoryLeaseRefusalRepository(),
    )
    reclaim = _reclaim()

    with caplog.at_level(logging.DEBUG):
        _record(service, reclaim)

    loud = [r for r in caplog.records if r.levelno >= logging.WARNING]

    assert len(loud) == 1
    assert loud[0].levelno == logging.WARNING
    assert str(reclaim.lease_id) in loud[0].getMessage()


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError, OSError])
def test_a_failed_save_does_not_raise(error_type: type[Exception]) -> None:
    reclaims = InMemoryLeaseReclaimRepository()
    reclaim = _reclaim()
    reclaims.save(reclaim)
    service = _service(reclaims, _FailingRefusals(error_type("database down")))

    _record(service, reclaim)


def test_a_failed_save_logs_one_warning_with_the_lease_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reclaims = InMemoryLeaseReclaimRepository()
    reclaim = _reclaim()
    reclaims.save(reclaim)
    service = _service(reclaims, _FailingRefusals(RuntimeError("database down")))

    with caplog.at_level(logging.DEBUG):
        _record(service, reclaim)

    loud = [r for r in caplog.records if r.levelno >= logging.WARNING]

    assert len(loud) == 1
    assert loud[0].levelno == logging.WARNING
    assert str(reclaim.lease_id) in loud[0].getMessage()


def test_a_save_that_works_logs_nothing_above_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reclaims = InMemoryLeaseReclaimRepository()
    reclaim = _reclaim()
    reclaims.save(reclaim)
    service = _service(reclaims, InMemoryLeaseRefusalRepository())

    with caplog.at_level(logging.DEBUG):
        _record(service, reclaim)

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_a_lease_without_a_reclaim_record_logs_nothing_above_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    refusals = _SpyRefusals()
    reclaim = _reclaim()

    with caplog.at_level(logging.DEBUG):
        _record(_service(InMemoryLeaseReclaimRepository(), refusals), reclaim)

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert refusals.saved == []
