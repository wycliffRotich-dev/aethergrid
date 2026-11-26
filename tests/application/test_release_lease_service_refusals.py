from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.application.services.release_lease_service import (
    ReleaseLeaseService,
)
from app.domain.entities.lease import Lease
from app.domain.entities.worker import Worker
from app.domain.enums.lease_refusal_operation import LeaseRefusalOperation
from app.domain.enums.lease_refusal_reason import LeaseRefusalReason
from app.domain.exceptions.lease_not_found_error import (
    LeaseNotFoundError,
)
from app.domain.exceptions.no_active_lease_error import (
    NoActiveLeaseError,
)
from app.domain.exceptions.worker_not_found_error import (
    WorkerNotFoundError,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_lease_repository import (
    InMemoryLeaseRepository,
)
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)
from tests.support.nodes import make_node
from tests.support.workers import make_worker


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


class _LeaseRepositoryThatLosesTheDelete(InMemoryLeaseRepository):
    def delete_by_id(self, lease_id: UUID, tenant_id: TenantId) -> bool:
        return False


def _worker() -> Worker:
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    return make_worker(id=WorkerId.new(), node=node)


def _lease(worker: Worker) -> Lease:
    return Lease.create(
        worker_id=worker.id,
        job_id=JobId.new(),
        tenant_id=worker.tenant_id,
    )


def _service(lease_repository, worker_repository, recorder) -> ReleaseLeaseService:
    return ReleaseLeaseService(
        lease_repository=lease_repository,
        worker_repository=worker_repository,
        record_lease_refusal_service=recorder,
    )


def _expected(worker: Worker, lease_id: UUID, reason) -> dict[str, object]:
    return {
        "lease_id": lease_id,
        "tenant_id": worker.tenant_id,
        "worker_id": worker.id,
        "operation": LeaseRefusalOperation.RELEASE,
        "reason": reason,
    }


def test_a_worker_without_a_lease_records_a_refusal_for_no_active_lease() -> None:
    worker = _worker()
    recorder = _SpyRecorder()
    service = _service(
        InMemoryLeaseRepository(),
        InMemoryWorkerRepository([worker]),
        recorder,
    )
    lease_id = uuid4()

    with pytest.raises(NoActiveLeaseError):
        service.execute(worker.id, lease_id, worker.tenant_id)

    assert recorder.calls == [
        _expected(worker, lease_id, LeaseRefusalReason.NO_ACTIVE_LEASE)
    ]


def test_another_lease_on_record_records_a_refusal_for_the_lease_sent() -> None:
    worker = _worker()
    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(_lease(worker))
    recorder = _SpyRecorder()
    service = _service(
        lease_repository,
        InMemoryWorkerRepository([worker]),
        recorder,
    )
    sent_lease_id = uuid4()

    with pytest.raises(LeaseNotFoundError):
        service.execute(worker.id, sent_lease_id, worker.tenant_id)

    assert recorder.calls == [
        _expected(worker, sent_lease_id, LeaseRefusalReason.LEASE_NOT_CURRENT)
    ]
    assert lease_repository.get_by_worker_id(worker.id, worker.tenant_id) is not None


def test_a_delete_that_removes_nothing_records_a_refusal_for_the_lease_sent() -> None:
    worker = _worker()
    lease = _lease(worker)
    lease_repository = _LeaseRepositoryThatLosesTheDelete()
    lease_repository.save(lease)
    recorder = _SpyRecorder()
    service = _service(
        lease_repository,
        InMemoryWorkerRepository([worker]),
        recorder,
    )

    with pytest.raises(LeaseNotFoundError):
        service.execute(worker.id, lease.id, worker.tenant_id)

    assert recorder.calls == [
        _expected(worker, lease.id, LeaseRefusalReason.LEASE_NOT_CURRENT)
    ]


def test_a_release_that_works_records_nothing() -> None:
    worker = _worker()
    lease = _lease(worker)
    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)
    recorder = _SpyRecorder()
    service = _service(
        lease_repository,
        InMemoryWorkerRepository([worker]),
        recorder,
    )

    service.execute(worker.id, lease.id, worker.tenant_id)

    assert recorder.calls == []
    assert lease_repository.get_by_worker_id(worker.id, worker.tenant_id) is None


def test_a_missing_worker_records_nothing() -> None:
    worker = _worker()
    lease = _lease(worker)
    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)
    recorder = _SpyRecorder()
    service = _service(lease_repository, InMemoryWorkerRepository(), recorder)

    with pytest.raises(WorkerNotFoundError):
        service.execute(worker.id, lease.id, worker.tenant_id)

    assert recorder.calls == []
