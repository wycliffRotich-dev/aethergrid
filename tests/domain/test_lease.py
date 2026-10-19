from __future__ import annotations

from datetime import timedelta

from app.domain.entities.lease import (
    DEFAULT_LEASE_DURATION,
    Lease,
    utc_now,
)
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.worker_id import WorkerId


def create_lease() -> Lease:
    return Lease.create(
        worker_id=WorkerId.new(),
        job_id=JobId.new(),
        tenant_id=DEFAULT_TENANT_ID,
    )


def test_create_lease() -> None:
    lease = create_lease()

    assert lease.worker_id is not None
    assert lease.job_id is not None
    assert not lease.is_expired()


def test_expired_lease() -> None:
    lease = create_lease()

    lease.expires_at = (
        utc_now()
        - timedelta(seconds=1)
    )

    assert lease.is_expired()


def test_renew_extends_expiration() -> None:
    lease = create_lease()

    previous = lease.expires_at

    lease.renew()

    assert lease.expires_at > previous


def test_custom_lease_duration() -> None:
    lease = Lease.create(
        worker_id=WorkerId.new(),
        job_id=JobId.new(),
        tenant_id=DEFAULT_TENANT_ID,
        duration=timedelta(minutes=2),
    )

    assert (
        lease.expires_at - lease.acquired_at
    ) == timedelta(minutes=2)


def test_default_duration() -> None:
    lease = create_lease()

    assert (
        lease.expires_at - lease.acquired_at
    ) == DEFAULT_LEASE_DURATION
