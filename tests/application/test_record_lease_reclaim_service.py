from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from app.application.services.record_lease_reclaim_service import (
    RecordLeaseReclaimService,
)
from app.domain.entities.lease import Lease
from app.domain.entities.lease_reclaim import LeaseReclaim
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.enums.lease_recovery_path import LeaseRecoveryPath
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_lease_reclaim_repository import (
    InMemoryLeaseReclaimRepository,
)


class _SpyRepository(InMemoryLeaseReclaimRepository):
    def __init__(self) -> None:
        super().__init__()
        self.saved: list[LeaseReclaim] = []

    def save(self, record: LeaseReclaim) -> None:
        self.saved.append(record)
        super().save(record)


class _FailingRepository(InMemoryLeaseReclaimRepository):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    def save(self, record: LeaseReclaim) -> None:
        raise self._error


def _expired_lease() -> Lease:
    return Lease.create(
        worker_id=WorkerId.new(),
        job_id=JobId.new(),
        tenant_id=DEFAULT_TENANT_ID,
        duration=timedelta(seconds=-1),
    )


def test_record_saves_the_values_of_the_deleted_lease() -> None:
    repository = InMemoryLeaseReclaimRepository()
    service = RecordLeaseReclaimService(repository)
    lease = _expired_lease()

    service.record(lease, LeaseRecoveryPath.EXPIRED_LEASE)

    record = repository.get_by_lease_id(lease.id, lease.tenant_id)

    assert record is not None
    assert record.lease_id == lease.id
    assert record.id != lease.id
    assert record.tenant_id == lease.tenant_id
    assert record.worker_id == lease.worker_id
    assert record.job_id == lease.job_id
    assert record.lease_acquired_at == lease.acquired_at
    assert record.lease_expires_at == lease.expires_at


@pytest.mark.parametrize("path", list(LeaseRecoveryPath))
def test_record_stores_the_recovery_path_as_given(path: LeaseRecoveryPath) -> None:
    repository = InMemoryLeaseReclaimRepository()
    service = RecordLeaseReclaimService(repository)
    lease = _expired_lease()

    service.record(lease, path)

    record = repository.get_by_lease_id(lease.id, lease.tenant_id)

    assert record is not None
    assert record.recovered_by is path


def test_one_call_saves_exactly_one_record() -> None:
    repository = _SpyRepository()
    service = RecordLeaseReclaimService(repository)

    service.record(_expired_lease(), LeaseRecoveryPath.OFFLINE_NODE)

    assert len(repository.saved) == 1


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError, OSError])
def test_a_failed_save_does_not_raise(error_type: type[Exception]) -> None:
    service = RecordLeaseReclaimService(_FailingRepository(error_type("database down")))

    service.record(_expired_lease(), LeaseRecoveryPath.EXPIRED_LEASE)


def test_a_failed_save_logs_one_warning_with_the_lease_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = RecordLeaseReclaimService(_FailingRepository(RuntimeError("database down")))
    lease = _expired_lease()

    with caplog.at_level(logging.DEBUG):
        service.record(lease, LeaseRecoveryPath.EXPIRED_LEASE)

    loud = [record for record in caplog.records if record.levelno >= logging.WARNING]

    assert len(loud) == 1
    assert loud[0].levelno == logging.WARNING
    assert str(lease.id) in loud[0].getMessage()


def test_a_save_that_works_logs_nothing_above_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = RecordLeaseReclaimService(InMemoryLeaseReclaimRepository())

    with caplog.at_level(logging.DEBUG):
        service.record(_expired_lease(), LeaseRecoveryPath.EXPIRED_LEASE)

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
