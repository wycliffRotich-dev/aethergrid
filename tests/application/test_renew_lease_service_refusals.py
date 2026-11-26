from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.application.services.renew_lease_service import (
    RenewLeaseService,
)
from app.domain.entities.lease import Lease
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.enums.lease_refusal_operation import LeaseRefusalOperation
from app.domain.enums.lease_refusal_reason import LeaseRefusalReason
from app.domain.exceptions.lease_not_found_error import (
    LeaseNotFoundError,
)
from app.domain.exceptions.no_active_lease_error import (
    NoActiveLeaseError,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_lease_repository import (
    InMemoryLeaseRepository,
)


class _SpyRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def record(
        self,
        *,
        lease_id,
        tenant_id,
        worker_id,
        operation,
        reason,
    ) -> None:
        self.calls.append(
            {
                "lease_id": lease_id,
                "tenant_id": tenant_id,
                "worker_id": worker_id,
                "operation": operation,
                "reason": reason,
            }
        )


def _service(repository, recorder) -> RenewLeaseService:
    return RenewLeaseService(
        lease_repository=repository,
        record_lease_refusal_service=recorder,
    )


def _lease(worker_id: WorkerId, tenant_id: TenantId = DEFAULT_TENANT_ID) -> Lease:
    return Lease.create(
        worker_id=worker_id,
        job_id=JobId.new(),
        tenant_id=tenant_id,
        duration=timedelta(minutes=1),
    )


def test_a_worker_without_a_lease_records_a_refusal_for_no_active_lease() -> None:
    recorder = _SpyRecorder()
    service = _service(InMemoryLeaseRepository(), recorder)
    worker_id = WorkerId.new()
    lease_id = uuid4()

    with pytest.raises(NoActiveLeaseError):
        service.execute(
            worker_id,
            expected_lease_id=lease_id,
            tenant_id=DEFAULT_TENANT_ID,
        )

    assert recorder.calls == [
        {
            "lease_id": lease_id,
            "tenant_id": DEFAULT_TENANT_ID,
            "worker_id": worker_id,
            "operation": LeaseRefusalOperation.RENEW,
            "reason": LeaseRefusalReason.NO_ACTIVE_LEASE,
        }
    ]


def test_another_lease_on_record_records_a_refusal_for_the_lease_sent() -> None:
    repository = InMemoryLeaseRepository()
    recorder = _SpyRecorder()
    worker_id = WorkerId.new()
    repository.save(_lease(worker_id))
    sent_lease_id = uuid4()

    with pytest.raises(LeaseNotFoundError):
        _service(repository, recorder).execute(
            worker_id,
            expected_lease_id=sent_lease_id,
            tenant_id=DEFAULT_TENANT_ID,
        )

    assert recorder.calls == [
        {
            "lease_id": sent_lease_id,
            "tenant_id": DEFAULT_TENANT_ID,
            "worker_id": worker_id,
            "operation": LeaseRefusalOperation.RENEW,
            "reason": LeaseRefusalReason.LEASE_NOT_CURRENT,
        }
    ]


def test_a_renewal_that_works_records_nothing() -> None:
    repository = InMemoryLeaseRepository()
    recorder = _SpyRecorder()
    worker_id = WorkerId.new()
    lease = _lease(worker_id)
    repository.save(lease)

    _service(repository, recorder).execute(
        worker_id,
        expected_lease_id=lease.id,
        tenant_id=DEFAULT_TENANT_ID,
    )

    assert recorder.calls == []


def test_a_lease_in_another_tenant_records_the_tenant_of_the_call() -> None:
    repository = InMemoryLeaseRepository()
    recorder = _SpyRecorder()
    lease = _lease(WorkerId.new(), tenant_id=TenantId.new())
    repository.save(lease)
    caller_tenant = TenantId.new()

    with pytest.raises(NoActiveLeaseError):
        _service(repository, recorder).execute(
            lease.worker_id,
            expected_lease_id=lease.id,
            tenant_id=caller_tenant,
        )

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["tenant_id"] == caller_tenant
    assert recorder.calls[0]["reason"] is LeaseRefusalReason.NO_ACTIVE_LEASE
