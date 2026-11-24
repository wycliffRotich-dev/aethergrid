"""ADR 0107: registering a worker keeps the record of the lease it deletes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from app.application.services.create_worker_service import (
    CreateWorkerService,
)
from app.application.services.record_lease_reclaim_service import (
    RecordLeaseReclaimService,
)
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.lease_reclaim import LeaseReclaim
from app.domain.entities.node import Node
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.entities.worker import Worker
from app.domain.enums.lease_recovery_path import LeaseRecoveryPath
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from app.infrastructure.repositories.in_memory_lease_reclaim_repository import (
    InMemoryLeaseReclaimRepository,
)
from app.infrastructure.repositories.in_memory_lease_repository import (
    InMemoryLeaseRepository,
)
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node
from tests.support.workers import make_worker


@dataclass
class _World:
    service: CreateWorkerService
    node: Node
    worker: Worker
    job: Job | None
    lease: Lease | None
    job_repository: InMemoryJobRepository
    lease_repository: InMemoryLeaseRepository
    worker_repository: InMemoryWorkerRepository
    records: InMemoryLeaseReclaimRepository


class _SpyRecords(InMemoryLeaseReclaimRepository):
    def __init__(self) -> None:
        super().__init__()
        self.saved: list[LeaseReclaim] = []
        self.on_save: Callable[[LeaseReclaim], None] | None = None

    def save(self, record: LeaseReclaim) -> None:
        self.saved.append(record)
        if self.on_save is not None:
            self.on_save(record)
        super().save(record)


class _FailingRecords(InMemoryLeaseReclaimRepository):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def save(self, record: LeaseReclaim) -> None:
        self.attempts += 1
        raise RuntimeError("the table is gone")


def _world(
    tenant_id: TenantId = DEFAULT_TENANT_ID,
    *,
    job_kind: str = "running",
    with_lease: bool = True,
    registered: bool = True,
    records: InMemoryLeaseReclaimRepository | None = None,
    with_recorder: bool = True,
) -> _World:
    if records is None:
        records = InMemoryLeaseReclaimRepository()

    node = make_node(
        id=NodeId.new(),
        tenant_id=tenant_id,
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )
    worker = make_worker(id=WorkerId.new(), node=node)
    worker.ready()

    job: Job | None = None
    if job_kind == "running":
        job = make_job(id=JobId.new(), tenant_id=tenant_id, max_retries=1)
        job.queue()
        job.assign_to(node.id)
        node.allocate(job.resources)
        worker.accept(job)
        worker.start()
    elif job_kind == "queued":
        job = make_job(id=JobId.new(), tenant_id=tenant_id, max_retries=1)
        job.queue()
        worker.running_job = job

    lease: Lease | None = None
    lease_repository = InMemoryLeaseRepository()
    if job is not None and with_lease:
        lease = Lease.create(
            worker_id=worker.id,
            job_id=job.id,
            tenant_id=tenant_id,
            duration=timedelta(seconds=30),
        )
        lease_repository.save(lease)

    job_repository = InMemoryJobRepository([job] if job is not None else [])
    worker_repository = InMemoryWorkerRepository([worker] if registered else [])

    kwargs: dict[str, Any] = {}
    if with_recorder:
        kwargs["record_lease_reclaim_service"] = RecordLeaseReclaimService(records)

    service = CreateWorkerService(
        worker_repository=worker_repository,
        job_repository=job_repository,
        lease_repository=lease_repository,
        node_repository=InMemoryNodeRepository([node]),
        **kwargs,
    )

    return _World(
        service,
        node,
        worker,
        job,
        lease,
        job_repository,
        lease_repository,
        worker_repository,
        records,
    )


def test_the_record_holds_the_deleted_lease_and_the_worker_registered_path() -> None:
    world = _world()
    assert world.lease is not None
    assert world.job is not None

    world.service.execute(node=world.node)

    record = world.records.get_by_lease_id(world.lease.id, world.lease.tenant_id)

    assert record is not None
    assert record.recovered_by is LeaseRecoveryPath.WORKER_REGISTERED
    assert record.lease_id == world.lease.id
    assert record.id != world.lease.id
    assert record.tenant_id == world.lease.tenant_id
    assert record.worker_id == world.worker.id
    assert record.job_id == world.job.id
    assert record.lease_acquired_at == world.lease.acquired_at
    assert record.lease_expires_at == world.lease.expires_at


def test_the_record_is_saved_exactly_once() -> None:
    records = _SpyRecords()
    world = _world(records=records)
    assert world.lease is not None

    world.service.execute(node=world.node)

    assert len(records.saved) == 1
    assert records.saved[0].lease_id == world.lease.id


def test_a_job_with_no_lease_is_reclaimed_and_not_recorded() -> None:
    records = _SpyRecords()
    world = _world(with_lease=False, records=records)
    assert world.job is not None

    world.service.execute(node=world.node)

    stored = world.job_repository.get_by_id(world.job.id, DEFAULT_TENANT_ID)

    assert stored is not None
    assert stored.is_queued()
    assert stored.retry_count == 1
    assert records.saved == []


def test_a_job_that_cannot_be_reclaimed_is_not_recorded() -> None:
    records = _SpyRecords()
    world = _world(job_kind="queued", records=records)
    assert world.job is not None

    world.service.execute(node=world.node)

    stored = world.job_repository.get_by_id(world.job.id, DEFAULT_TENANT_ID)

    assert stored is not None
    assert stored.is_queued()
    assert stored.retry_count == 0
    assert records.saved == []


def test_the_record_is_kept_in_the_tenant_of_the_lease() -> None:
    tenant = TenantId.new()
    other_tenant = TenantId.new()
    world = _world(tenant)
    assert world.lease is not None

    world.service.execute(node=world.node)

    record = world.records.get_by_lease_id(world.lease.id, tenant)

    assert record is not None
    assert record.tenant_id == tenant
    assert world.records.get_by_lease_id(world.lease.id, DEFAULT_TENANT_ID) is None
    assert world.records.get_by_lease_id(world.lease.id, other_tenant) is None


def test_a_failed_save_leaves_the_reclaim_and_the_recovered_worker() -> None:
    records = _FailingRecords()
    world = _world(records=records)
    assert world.job is not None

    registered = world.service.execute(node=world.node)

    stored = world.job_repository.get_by_id(world.job.id, DEFAULT_TENANT_ID)

    assert records.attempts == 1
    assert stored is not None
    assert stored.is_queued()
    assert stored.retry_count == 1
    assert world.lease_repository.get_by_job_id(world.job.id, DEFAULT_TENANT_ID) is None
    assert registered.is_idle()
    assert registered.running_job is None


def test_the_record_is_saved_after_the_reclaim() -> None:
    records = _SpyRecords()
    world = _world(records=records)
    assert world.job is not None
    job = world.job
    seen: list[tuple[bool, bool]] = []

    def capture(record: LeaseReclaim) -> None:
        stored = world.job_repository.get_by_id(job.id, DEFAULT_TENANT_ID)
        lease = world.lease_repository.get_by_job_id(job.id, DEFAULT_TENANT_ID)
        seen.append((stored is not None and stored.is_queued(), lease is None))

    records.on_save = capture

    world.service.execute(node=world.node)

    assert seen == [(True, True)]


def test_a_first_registration_records_nothing() -> None:
    records = _SpyRecords()
    world = _world(job_kind="none", registered=False, records=records)

    created = world.service.execute(node=world.node)

    assert created.is_idle()
    assert records.saved == []


def test_a_reregistered_worker_with_no_job_records_nothing() -> None:
    records = _SpyRecords()
    world = _world(job_kind="none", records=records)

    reregistered = world.service.execute(node=world.node)

    assert reregistered.id == world.worker.id
    assert records.saved == []


def test_a_service_built_without_the_recorder_behaves_as_before() -> None:
    world = _world(with_recorder=False)
    assert world.lease is not None
    assert world.job is not None

    registered = world.service.execute(node=world.node)

    stored = world.job_repository.get_by_id(world.job.id, DEFAULT_TENANT_ID)

    assert registered.is_idle()
    assert stored is not None
    assert stored.is_queued()
    assert stored.retry_count == 1
    assert world.lease_repository.get_by_job_id(world.job.id, DEFAULT_TENANT_ID) is None
    assert world.records.get_by_lease_id(world.lease.id, world.lease.tenant_id) is None
