from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.entities.lease import Lease
from app.domain.entities.lease_reclaim import LeaseReclaim
from app.domain.enums.lease_recovery_path import LeaseRecoveryPath
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId


def _expired_lease() -> Lease:
    return Lease.create(
        worker_id=WorkerId.new(),
        job_id=JobId.new(),
        tenant_id=TenantId.new(),
        duration=timedelta(seconds=-1),
    )


def test_the_recovery_paths_match_what_the_table_accepts() -> None:
    """
    The values are the ones the check constraint of migration 0008 lets
    through (ADR 0107, decision 1). A change here needs a migration.
    """
    assert {path.name: path.value for path in LeaseRecoveryPath} == {
        "EXPIRED_LEASE": "expired_lease",
        "OFFLINE_NODE": "offline_node",
        "WORKER_REGISTERED": "worker_registered",
    }


def test_a_record_copies_the_lease_it_was_made_from() -> None:
    lease = _expired_lease()

    record = LeaseReclaim.record(
        lease=lease,
        recovered_by=LeaseRecoveryPath.EXPIRED_LEASE,
    )

    assert record.lease_id == lease.id
    assert record.tenant_id == lease.tenant_id
    assert record.worker_id == lease.worker_id
    assert record.job_id == lease.job_id
    assert record.lease_acquired_at == lease.acquired_at
    assert record.lease_expires_at == lease.expires_at
    assert record.recovered_by is LeaseRecoveryPath.EXPIRED_LEASE


def test_a_record_carries_each_recovery_path() -> None:
    lease = _expired_lease()

    for path in LeaseRecoveryPath:
        record = LeaseReclaim.record(lease=lease, recovered_by=path)

        assert record.recovered_by is path


def test_a_record_has_an_id_of_its_own() -> None:
    lease = _expired_lease()

    first = LeaseReclaim.record(
        lease=lease,
        recovered_by=LeaseRecoveryPath.EXPIRED_LEASE,
    )
    second = LeaseReclaim.record(
        lease=lease,
        recovered_by=LeaseRecoveryPath.EXPIRED_LEASE,
    )

    assert first.id != lease.id
    assert second.id != lease.id
    assert first.id != second.id


def test_reclaimed_at_is_the_time_of_the_call() -> None:
    lease = _expired_lease()

    before = datetime.now(UTC)
    record = LeaseReclaim.record(
        lease=lease,
        recovered_by=LeaseRecoveryPath.EXPIRED_LEASE,
    )
    after = datetime.now(UTC)

    assert record.reclaimed_at.tzinfo is not None
    assert before <= record.reclaimed_at <= after


def test_a_record_is_immutable() -> None:
    record = LeaseReclaim.record(
        lease=_expired_lease(),
        recovered_by=LeaseRecoveryPath.EXPIRED_LEASE,
    )

    for field in fields(record):
        with pytest.raises(FrozenInstanceError):
            setattr(record, field.name, None)


def test_recording_does_not_change_the_lease() -> None:
    lease = _expired_lease()
    snapshot = copy.copy(lease)

    LeaseReclaim.record(
        lease=lease,
        recovered_by=LeaseRecoveryPath.EXPIRED_LEASE,
    )

    assert lease == snapshot
