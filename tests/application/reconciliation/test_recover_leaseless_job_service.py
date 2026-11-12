from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from app.application.reconciliation.reconciliation_loop import (
    ReconciliationLoop,
)
from app.application.reconciliation.recover_expired_lease_service import (
    RecoverExpiredLeaseService,
)
from app.application.reconciliation.recover_leaseless_job_service import (
    RecoverLeaselessJobService,
)
from app.application.reconciliation.recover_offline_node_service import (
    RecoverOfflineNodeService,
)
from app.application.services.mark_dead_workers_service import (
    MarkDeadWorkersService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.node import Node
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.entities.worker import Worker
from app.domain.enums.job_status import JobStatus
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
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

CAPACITY = 8


class StoredCopyJobRepository(InMemoryJobRepository):
    """
    Hands out copies, as a database does. The in-memory repository
    returns the stored object, so a change that was never saved is
    still visible through it and would hide the failure under test.
    """

    fail_next_save = False
    fail_save_of: JobId | None = None

    def __init__(self, jobs: list[Job]) -> None:
        super().__init__([copy.deepcopy(job) for job in jobs])

    def save(self, job: Job) -> None:
        if self.fail_next_save:
            self.fail_next_save = False
            raise RuntimeError("the write was lost")

        if job.id == self.fail_save_of:
            self.fail_save_of = None
            raise RuntimeError("the write was lost")

        super().save(copy.deepcopy(job))

    def get_by_id(self, job_id, tenant_id):  # type: ignore[no-untyped-def]
        return copy.deepcopy(super().get_by_id(job_id, tenant_id))


class Cluster:
    """
    One node, one worker and one running job that holds a lease.
    """

    def __init__(self, *, max_retries: int = 3) -> None:
        self.node: Node = make_node(
            id=NodeId.new(),
            capacity=ResourceRequirements(
                cpu_cores=CAPACITY,
                memory_mib=16384,
                vram_mib=0,
            ),
        )
        self.worker: Worker = make_worker(node=self.node)
        self.worker.ready()

        job = make_job(max_retries=max_retries)
        job.queue()
        job.assign_to(self.node.id)
        self.node.allocate(job.resources)
        self.worker.accept(job)
        self.worker.start()

        self.lease = Lease.create(
            worker_id=self.worker.id,
            job_id=job.id,
            tenant_id=self.worker.tenant_id,
            duration=timedelta(seconds=-1),
        )

        self.jobs = StoredCopyJobRepository([job])
        self.leases = InMemoryLeaseRepository()
        self.leases.save(self.lease)
        self.workers = InMemoryWorkerRepository([self.worker])
        self.nodes = InMemoryNodeRepository([self.node])
        self.events = InMemoryEventRepository()
        self.job_id = job.id

    def stored_job(self) -> Job:
        job = self.jobs.get_by_id(self.job_id, DEFAULT_TENANT_ID)
        assert job is not None
        return job

    def event_types(self) -> list[str]:
        return [
            event.event_type
            for event in self.events.list(DEFAULT_TENANT_ID)
        ]

    def free_cpu(self) -> int:
        node = self.nodes.get_by_id(self.node.id, DEFAULT_TENANT_ID)
        assert node is not None
        return node.available.cpu_cores

    def sweep(self) -> RecoverLeaselessJobService:
        return RecoverLeaselessJobService(
            job_repository=self.jobs,
            lease_repository=self.leases,
            worker_repository=self.workers,
            node_repository=self.nodes,
            record_job_events_service=RecordJobEventsService(self.events),
        )

    def loop(self) -> ReconciliationLoop:
        return ReconciliationLoop(
            mark_dead_workers_service=MarkDeadWorkersService(
                worker_repository=self.workers,
            ),
            recover_expired_lease_service=RecoverExpiredLeaseService(
                worker_repository=self.workers,
                job_repository=self.jobs,
                lease_repository=self.leases,
                node_repository=self.nodes,
            ),
            recover_offline_node_service=RecoverOfflineNodeService(
                node_repository=self.nodes,
                worker_repository=self.workers,
                job_repository=self.jobs,
                lease_repository=self.leases,
            ),
            recover_leaseless_job_service=self.sweep(),
        )

    def lose_the_lease(self) -> None:
        self.leases.delete(self.job_id, DEFAULT_TENANT_ID)


def test_a_failed_job_save_after_the_lease_delete_is_repaired() -> None:
    """
    The failure this service exists for. Expired-lease recovery
    deletes the lease and then fails to save the job. Before ADR 0096
    the job stayed RUNNING for good, with its capacity allocated.
    """
    cluster = Cluster()
    loop = cluster.loop()

    cluster.jobs.fail_next_save = True
    loop.execute()

    assert cluster.leases.list_across_tenants() == []
    assert cluster.stored_job().status is JobStatus.RUNNING
    assert cluster.free_cpu() == CAPACITY - 1

    loop.execute()
    loop.execute()

    job = cluster.stored_job()
    assert job.status is JobStatus.QUEUED
    assert job.retry_count == 1
    assert job.assigned_node_id is None
    assert cluster.free_cpu() == CAPACITY


def test_a_job_without_a_lease_is_not_reclaimed_on_the_first_sighting() -> None:
    cluster = Cluster()
    cluster.lose_the_lease()
    sweep = cluster.sweep()

    sweep.execute()

    assert cluster.stored_job().status is JobStatus.RUNNING
    assert cluster.free_cpu() == CAPACITY - 1


def test_a_job_seen_without_a_lease_twice_is_reclaimed_once() -> None:
    cluster = Cluster()
    cluster.lose_the_lease()
    sweep = cluster.sweep()

    sweep.execute()
    sweep.execute()
    sweep.execute()
    sweep.execute()

    job = cluster.stored_job()
    assert job.status is JobStatus.QUEUED
    assert job.retry_count == 1
    assert cluster.free_cpu() == CAPACITY

    stored = cluster.workers.get_by_id(
        cluster.worker.id,
        cluster.worker.tenant_id,
    )
    assert stored is not None
    assert stored.is_idle()
    assert stored.running_job is None

    types = cluster.event_types()
    assert types.count("JobReclaimed") == 1


def test_a_job_whose_lease_returns_between_passes_is_left_alone() -> None:
    """
    A pass that reads a job between the release of its lease and the
    save of its outcome sees no lease. The job is not abandoned.
    """
    cluster = Cluster()
    live = Lease.create(
        worker_id=cluster.worker.id,
        job_id=cluster.job_id,
        tenant_id=cluster.worker.tenant_id,
    )
    cluster.lose_the_lease()
    sweep = cluster.sweep()

    sweep.execute()
    cluster.leases.save(live)
    sweep.execute()
    sweep.execute()

    assert cluster.stored_job().status is JobStatus.RUNNING
    assert cluster.free_cpu() == CAPACITY - 1


def test_a_job_that_finished_between_passes_is_left_alone() -> None:
    cluster = Cluster()
    cluster.lose_the_lease()
    sweep = cluster.sweep()

    sweep.execute()

    job = cluster.stored_job()
    job.complete(exit_code=0)
    cluster.jobs.save(job)

    sweep.execute()

    stored = cluster.stored_job()
    assert stored.status is JobStatus.COMPLETED
    assert stored.retry_count == 0


def test_a_job_with_a_live_lease_is_never_reclaimed() -> None:
    cluster = Cluster()
    cluster.leases.delete(cluster.job_id, DEFAULT_TENANT_ID)
    cluster.leases.save(
        Lease.create(
            worker_id=cluster.worker.id,
            job_id=cluster.job_id,
            tenant_id=cluster.worker.tenant_id,
        )
    )
    sweep = cluster.sweep()

    for _ in range(5):
        sweep.execute()

    assert cluster.stored_job().status is JobStatus.RUNNING


def test_a_queued_job_has_no_lease_and_is_not_touched() -> None:
    cluster = Cluster()
    job = cluster.stored_job()
    job.reclaim()
    cluster.jobs.save(job)
    cluster.lose_the_lease()
    sweep = cluster.sweep()

    for _ in range(3):
        sweep.execute()

    stored = cluster.stored_job()
    assert stored.status is JobStatus.QUEUED
    assert stored.retry_count == 1


def test_a_job_out_of_retries_fails_instead_of_requeuing() -> None:
    cluster = Cluster(max_retries=0)
    cluster.lose_the_lease()
    sweep = cluster.sweep()

    sweep.execute()
    sweep.execute()

    assert cluster.stored_job().status is JobStatus.FAILED
    assert cluster.free_cpu() == CAPACITY


def test_a_cancelling_job_without_a_lease_is_cancelled_not_retried() -> None:
    cluster = Cluster()
    job = cluster.stored_job()
    job.request_cancellation()
    cluster.jobs.save(job)
    cluster.lose_the_lease()
    sweep = cluster.sweep()

    sweep.execute()
    sweep.execute()

    stored = cluster.stored_job()
    assert stored.status is JobStatus.CANCELLED
    assert stored.retry_count == 0
    assert cluster.free_cpu() == CAPACITY

    types = cluster.event_types()
    assert types == ["JobCancelled"]


def test_a_job_that_cannot_be_reclaimed_does_not_stop_the_others() -> None:
    cluster = Cluster()
    cluster.lose_the_lease()

    other = make_job(max_retries=3)
    other.queue()
    other.assign_to(cluster.node.id)
    cluster.node.allocate(other.resources)
    cluster.nodes.save(cluster.node)
    cluster.jobs.save(other)

    sweep = cluster.sweep()
    sweep.execute()

    cluster.jobs.fail_save_of = cluster.job_id
    sweep.execute()

    stored_other = cluster.jobs.get_by_id(other.id, DEFAULT_TENANT_ID)
    assert stored_other is not None
    assert stored_other.status is JobStatus.QUEUED
    assert cluster.stored_job().status is JobStatus.RUNNING

    sweep.execute()

    assert cluster.stored_job().status is JobStatus.QUEUED


def test_an_error_on_one_job_is_logged_and_the_next_pass_retries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cluster = Cluster()
    cluster.lose_the_lease()
    sweep = cluster.sweep()
    sweep.execute()

    cluster.jobs.fail_next_save = True
    with caplog.at_level("ERROR"):
        sweep.execute()

    assert "holds no lease" in caplog.text
    assert cluster.stored_job().status is JobStatus.RUNNING

    sweep.execute()

    assert cluster.stored_job().status is JobStatus.QUEUED
