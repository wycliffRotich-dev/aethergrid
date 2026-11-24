"""ADR 0107: the offline node path keeps the record of the lease it deletes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.reconciliation.recover_offline_node_service import (
    RecoverOfflineNodeService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.application.services.record_lease_reclaim_service import (
    RecordLeaseReclaimService,
)
from app.domain.entities.event import Event
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.lease_reclaim import LeaseReclaim
from app.domain.entities.node import Node
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.entities.worker import Worker
from app.domain.enums.job_status import JobStatus
from app.domain.enums.lease_recovery_path import LeaseRecoveryPath
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)
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

_EXPIRED = timedelta(seconds=-1)


@dataclass
class _Party:
    node: Node
    worker: Worker
    job: Job
    lease: Lease | None


@dataclass
class _World:
    service: RecoverOfflineNodeService
    job_repository: InMemoryJobRepository
    lease_repository: InMemoryLeaseRepository
    events: InMemoryEventRepository
    records: InMemoryLeaseReclaimRepository


class _SpyRecords(InMemoryLeaseReclaimRepository):
    def __init__(self, order: list[str] | None = None) -> None:
        super().__init__()
        self.saved: list[LeaseReclaim] = []
        self.on_save: Callable[[LeaseReclaim], None] | None = None
        self._order = order

    def save(self, record: LeaseReclaim) -> None:
        self.saved.append(record)
        if self._order is not None:
            self._order.append("record")
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


class _OrderedEvents(InMemoryEventRepository):
    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self._order = order

    def save(self, event: Event) -> None:
        self._order.append("event")
        super().save(event)


class _RenewsLeaseBeforeDelete(InMemoryLeaseRepository):
    """
    Renews the lease just before delete_if_expired runs, so the delete
    is the step that refuses it.
    """

    def delete_if_expired(self, job_id: JobId, tenant_id: TenantId) -> bool:
        lease = self.get_by_job_id(job_id, tenant_id)

        if lease is not None:
            self.renew(lease.id, timedelta(seconds=30), tenant_id)

        return super().delete_if_expired(job_id, tenant_id)


def _party(
    tenant_id: TenantId = DEFAULT_TENANT_ID,
    *,
    lease: str = "expired",
) -> _Party:
    node = make_node(
        id=NodeId.new(),
        tenant_id=tenant_id,
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )
    node.last_seen_at = datetime.now(UTC) - timedelta(minutes=2)

    worker = make_worker(id=WorkerId.new(), node=node)
    worker.ready()

    job = make_job(id=JobId.new(), tenant_id=tenant_id, max_retries=1)
    job.queue()
    job.assign_to(node.id)
    node.allocate(job.resources)
    worker.accept(job)
    worker.start()

    held: Lease | None = None
    if lease == "expired":
        held = Lease.create(
            worker_id=worker.id,
            job_id=job.id,
            tenant_id=tenant_id,
            duration=_EXPIRED,
        )
    elif lease == "valid":
        held = Lease.create(
            worker_id=worker.id,
            job_id=job.id,
            tenant_id=tenant_id,
        )

    return _Party(node, worker, job, held)


def _world(
    party: _Party,
    *,
    records: InMemoryLeaseReclaimRepository | None = None,
    events: InMemoryEventRepository | None = None,
    lease_repository: InMemoryLeaseRepository | None = None,
    with_recorder: bool = True,
) -> _World:
    if records is None:
        records = InMemoryLeaseReclaimRepository()
    if events is None:
        events = InMemoryEventRepository()
    if lease_repository is None:
        lease_repository = InMemoryLeaseRepository()

    if party.lease is not None:
        lease_repository.save(party.lease)

    job_repository = InMemoryJobRepository([party.job])

    kwargs: dict[str, Any] = {}
    if with_recorder:
        kwargs["record_lease_reclaim_service"] = RecordLeaseReclaimService(records)

    service = RecoverOfflineNodeService(
        node_repository=InMemoryNodeRepository([party.node]),
        worker_repository=InMemoryWorkerRepository([party.worker]),
        job_repository=job_repository,
        lease_repository=lease_repository,
        record_job_events_service=RecordJobEventsService(event_repository=events),
        **kwargs,
    )

    return _World(service, job_repository, lease_repository, events, records)


def test_the_record_holds_the_deleted_lease_and_the_offline_node_path() -> None:
    party = _party()
    assert party.lease is not None
    world = _world(party)

    world.service.execute()

    record = world.records.get_by_lease_id(party.lease.id, party.lease.tenant_id)

    assert record is not None
    assert record.recovered_by is LeaseRecoveryPath.OFFLINE_NODE
    assert record.lease_id == party.lease.id
    assert record.id != party.lease.id
    assert record.tenant_id == party.lease.tenant_id
    assert record.worker_id == party.worker.id
    assert record.job_id == party.job.id
    assert record.lease_acquired_at == party.lease.acquired_at
    assert record.lease_expires_at == party.lease.expires_at


def test_the_record_is_saved_exactly_once() -> None:
    party = _party()
    assert party.lease is not None
    records = _SpyRecords()
    world = _world(party, records=records)

    world.service.execute()

    assert len(records.saved) == 1
    assert records.saved[0].lease_id == party.lease.id


def test_a_job_with_no_lease_is_reclaimed_and_not_recorded() -> None:
    party = _party(lease="none")
    records = _SpyRecords()
    world = _world(party, records=records)

    world.service.execute()

    stored = world.job_repository.get_by_id(party.job.id, DEFAULT_TENANT_ID)

    assert stored is not None
    assert stored.is_queued()
    assert stored.retry_count == 1
    assert [e.event_type for e in world.events.list(DEFAULT_TENANT_ID)] == ["JobReclaimed"]
    assert records.saved == []


def test_a_lease_that_is_still_valid_is_not_recorded() -> None:
    party = _party(lease="valid")
    records = _SpyRecords()
    world = _world(party, records=records)

    world.service.execute()

    assert records.saved == []
    assert world.lease_repository.get_by_job_id(party.job.id, DEFAULT_TENANT_ID) is not None


def test_a_lease_renewed_before_the_delete_is_not_recorded() -> None:
    party = _party()
    records = _SpyRecords()
    world = _world(
        party,
        records=records,
        lease_repository=_RenewsLeaseBeforeDelete(),
    )

    world.service.execute()

    assert records.saved == []


def test_the_record_is_kept_in_the_tenant_of_the_lease() -> None:
    tenant = TenantId.new()
    other_tenant = TenantId.new()
    party = _party(tenant)
    assert party.lease is not None
    world = _world(party)

    world.service.execute()

    record = world.records.get_by_lease_id(party.lease.id, tenant)

    assert record is not None
    assert record.tenant_id == tenant
    assert world.records.get_by_lease_id(party.lease.id, DEFAULT_TENANT_ID) is None
    assert world.records.get_by_lease_id(party.lease.id, other_tenant) is None


def test_a_failed_save_leaves_the_reclaim_and_the_event() -> None:
    party = _party()
    records = _FailingRecords()
    world = _world(party, records=records)

    world.service.execute()

    stored = world.job_repository.get_by_id(party.job.id, DEFAULT_TENANT_ID)

    assert records.attempts == 1
    assert stored is not None
    assert stored.is_queued()
    assert stored.retry_count == 1
    assert world.lease_repository.get_by_job_id(party.job.id, DEFAULT_TENANT_ID) is None
    assert [e.event_type for e in world.events.list(DEFAULT_TENANT_ID)] == ["JobReclaimed"]


def test_the_record_is_saved_before_the_event() -> None:
    order: list[str] = []
    party = _party()
    world = _world(
        party,
        records=_SpyRecords(order),
        events=_OrderedEvents(order),
    )

    world.service.execute()

    assert order == ["record", "event"]


def test_the_record_is_saved_after_the_reclaim() -> None:
    party = _party()
    records = _SpyRecords()
    world = _world(party, records=records)
    seen: list[tuple[bool, bool]] = []

    def capture(record: LeaseReclaim) -> None:
        stored = world.job_repository.get_by_id(party.job.id, DEFAULT_TENANT_ID)
        lease = world.lease_repository.get_by_job_id(party.job.id, DEFAULT_TENANT_ID)
        seen.append((stored is not None and stored.is_queued(), lease is None))

    records.on_save = capture

    world.service.execute()

    assert seen == [(True, True)]


def test_a_service_built_without_the_recorder_behaves_as_before() -> None:
    party = _party()
    assert party.lease is not None
    world = _world(party, with_recorder=False)

    world.service.execute()

    stored = world.job_repository.get_by_id(party.job.id, DEFAULT_TENANT_ID)

    assert stored is not None
    assert stored.is_queued()
    assert stored.retry_count == 1
    assert [e.event_type for e in world.events.list(DEFAULT_TENANT_ID)] == ["JobReclaimed"]
    assert world.records.get_by_lease_id(party.lease.id, party.lease.tenant_id) is None


def test_a_job_that_cannot_be_reclaimed_is_not_recorded() -> None:
    party = _party(lease="none")
    stuck = make_job(id=JobId.new(), max_retries=1)
    stuck.queue()
    party.worker.running_job = stuck
    lease = Lease.create(
        worker_id=party.worker.id,
        job_id=stuck.id,
        tenant_id=DEFAULT_TENANT_ID,
        duration=_EXPIRED,
    )
    records = _SpyRecords()
    world = _world(_Party(party.node, party.worker, stuck, lease), records=records)

    world.service.execute()

    stored = world.job_repository.get_by_id(stuck.id, DEFAULT_TENANT_ID)

    assert stored is not None
    assert stored.is_queued()
    assert stored.retry_count == 0
    assert world.lease_repository.get_by_job_id(stuck.id, DEFAULT_TENANT_ID) is None
    assert records.saved == []
    assert world.events.list(DEFAULT_TENANT_ID) == []


def test_a_cancelling_job_with_an_expired_lease_is_recorded_and_ends_cancelled() -> None:
    party = _party()
    assert party.lease is not None
    party.job.request_cancellation()
    records = _SpyRecords()
    world = _world(party, records=records)

    world.service.execute()

    stored = world.job_repository.get_by_id(party.job.id, DEFAULT_TENANT_ID)

    assert stored is not None
    assert stored.status is JobStatus.CANCELLED
    assert stored.retry_count == 0
    assert [e.event_type for e in world.events.list(DEFAULT_TENANT_ID)] == ["JobCancelled"]
    assert len(records.saved) == 1
    assert records.saved[0].lease_id == party.lease.id
    assert records.saved[0].recovered_by is LeaseRecoveryPath.OFFLINE_NODE


def test_a_cancelling_job_with_no_lease_ends_cancelled_and_is_not_recorded() -> None:
    party = _party(lease="none")
    party.job.request_cancellation()
    records = _SpyRecords()
    world = _world(party, records=records)

    world.service.execute()

    stored = world.job_repository.get_by_id(party.job.id, DEFAULT_TENANT_ID)

    assert stored is not None
    assert stored.status is JobStatus.CANCELLED
    assert stored.retry_count == 0
    assert [e.event_type for e in world.events.list(DEFAULT_TENANT_ID)] == ["JobCancelled"]
    assert records.saved == []


def test_a_running_job_with_an_expired_lease_is_recorded_with_job_reclaimed() -> None:
    party = _party()
    assert party.lease is not None
    records = _SpyRecords()
    world = _world(party, records=records)

    world.service.execute()

    stored = world.job_repository.get_by_id(party.job.id, DEFAULT_TENANT_ID)

    assert stored is not None
    assert stored.is_queued()
    assert stored.retry_count == 1
    assert [e.event_type for e in world.events.list(DEFAULT_TENANT_ID)] == ["JobReclaimed"]
    assert [r.lease_id for r in records.saved] == [party.lease.id]
