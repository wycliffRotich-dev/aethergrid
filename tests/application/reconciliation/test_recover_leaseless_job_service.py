from __future__ import annotations

from datetime import timedelta

import pytest

from app.application.reconciliation.reconciliation_loop import (
    ReconciliationLoop,
)
from app.application.reconciliation.recover_expired_lease_service import (
    RecoverExpiredLeaseService,
)
from app.application.reconciliation.recover_leaseless_job_service import (
    MAX_PASS_GAP_SECONDS,
    MIN_LEASELESS_AGE_SECONDS,
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
from app.application.services.release_lease_service import (
    ReleaseLeaseService,
)
from app.application.services.report_job_outcome_service import (
    ReportJobOutcomeService,
)
from app.domain.entities.event import Event
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
from app.infrastructure.repositories.in_memory_lease_repository import (
    InMemoryLeaseRepository,
)
from tests.support.copying_repositories import (
    CopyingJobRepository,
    CopyingNodeRepository,
    CopyingWorkerRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node
from tests.support.workers import make_worker

CAPACITY = 8
JOB_CPU = 1
OTHER_CPU = 2
MIN_AGE = MIN_LEASELESS_AGE_SECONDS


class Clock:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class LeaseAppearingAfterRead(InMemoryLeaseRepository):
    """
    Inserts a live lease at the exact point between the service's
    check that no lease exists and its write: the moment a read of a
    job's lease has returned nothing.
    """

    def __init__(self) -> None:
        super().__init__()
        self.appears: Lease | None = None
        self.fail_listing = False

    def get_by_job_id(self, job_id, tenant_id):  # type: ignore[no-untyped-def]
        found = super().get_by_job_id(job_id, tenant_id)

        if found is None and self.appears is not None:
            lease, self.appears = self.appears, None
            self.save(lease)

        return found

    def list_across_tenants(self) -> list[Lease]:
        if self.fail_listing:
            raise RuntimeError("the database is unreachable")

        return super().list_across_tenants()


class LosingEvents(InMemoryEventRepository):
    """Loses every event, as a failed write does."""

    def save(self, event: Event) -> None:
        raise RuntimeError("the event write was lost")


class NoSweep:
    """The loop without the new step, for the pre-fix behaviour."""

    def execute(self) -> None:
        return None


class Cluster:
    """
    One node with two workers. The main job holds one core and has the
    lease the tests take away. Another job holds two cores under a live
    lease, so that a node credited twice for the main job is visible:
    the node's free cores must be capacity minus the other job's, and
    an idle node would hide a second credit by clamping at capacity.
    """

    def __init__(
        self,
        *,
        max_retries: int = 3,
        main_lease_expired: bool = True,
        events: InMemoryEventRepository | None = None,
        min_age: float = MIN_AGE,
        max_gap: float = MAX_PASS_GAP_SECONDS,
    ) -> None:
        self.clock = Clock()
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
        job = make_job(
            max_retries=max_retries,
            resources=ResourceRequirements(
                cpu_cores=JOB_CPU, memory_mib=512, vram_mib=0
            ),
        )
        job.queue()
        job.assign_to(self.node.id)
        self.node.allocate(job.resources)
        self.worker.accept(job)
        self.worker.start()

        self.other_worker: Worker = make_worker(node=self.node)
        self.other_worker.ready()
        other = make_job(
            max_retries=3,
            resources=ResourceRequirements(
                cpu_cores=OTHER_CPU, memory_mib=1024, vram_mib=0
            ),
        )
        other.queue()
        other.assign_to(self.node.id)
        self.node.allocate(other.resources)
        self.other_worker.accept(other)
        self.other_worker.start()
        self.other_id = other.id

        self.lease = Lease.create(
            worker_id=self.worker.id,
            job_id=job.id,
            tenant_id=self.worker.tenant_id,
            duration=(
                timedelta(seconds=-1)
                if main_lease_expired
                else timedelta(hours=1)
            ),
        )
        self.leases = LeaseAppearingAfterRead()
        self.leases.save(self.lease)
        self.leases.save(
            Lease.create(
                worker_id=self.other_worker.id,
                job_id=other.id,
                tenant_id=self.other_worker.tenant_id,
                duration=timedelta(hours=1),
            )
        )

        self.jobs = CopyingJobRepository([job, other], self.leases)
        self.workers = CopyingWorkerRepository(
            [self.worker, self.other_worker]
        )
        self.nodes = CopyingNodeRepository([self.node])
        self.events = events or InMemoryEventRepository()
        self.job_id = job.id

        self.service = RecoverLeaselessJobService(
            job_repository=self.jobs,
            lease_repository=self.leases,
            worker_repository=self.workers,
            node_repository=self.nodes,
            record_job_events_service=RecordJobEventsService(self.events),
            clock=self.clock,
            min_age_seconds=min_age,
            max_pass_gap_seconds=max_gap,
        )

    def stored_job(self, job_id: JobId | None = None) -> Job:
        job = self.jobs.get_by_id(job_id or self.job_id, DEFAULT_TENANT_ID)
        assert job is not None
        return job

    def stored_worker(self, worker: Worker) -> Worker:
        stored = self.workers.get_by_id(worker.id, worker.tenant_id)
        assert stored is not None
        return stored

    def free_cpu(self) -> int:
        node = self.nodes.get_by_id(self.node.id, DEFAULT_TENANT_ID)
        assert node is not None
        return node.available.cpu_cores

    def event_types(self) -> list[str]:
        return [
            event.event_type for event in self.events.list(DEFAULT_TENANT_ID)
        ]

    def lose_the_lease(self) -> None:
        self.leases.delete(self.job_id, DEFAULT_TENANT_ID)

    def loop(self, sweep: object = None) -> ReconciliationLoop:
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
            recover_leaseless_job_service=(
                sweep or self.service  # type: ignore[arg-type]
            ),
        )

    def run_for(
        self,
        seconds: float,
        *,
        step: float = 10.0,
        runner=None,  # type: ignore[no-untyped-def]
    ) -> None:
        """
        Let time pass the way the tick does: many passes, none more
        than `step` seconds after the one before it.
        """
        run = runner or self.service.execute
        elapsed = 0.0
        while elapsed < seconds:
            self.clock.advance(step)
            run()
            elapsed += step


# --- the regression, and what the review found it must also do ---


def test_a_failed_job_save_after_the_lease_delete_is_repaired_once() -> None:
    """
    Expired-lease recovery deletes the lease and then fails to save the
    job. The job stays RUNNING with no lease. It is reclaimed once it
    has been without a lease for the minimum age, the node gets back
    only the main job's core, and more passes change nothing.
    """
    cluster = Cluster()
    loop = cluster.loop()

    cluster.jobs.fail_next_write = True
    loop.execute()

    assert cluster.leases.get_by_job_id(cluster.job_id, DEFAULT_TENANT_ID) is None
    assert cluster.stored_job().status is JobStatus.RUNNING
    assert cluster.free_cpu() == CAPACITY - JOB_CPU - OTHER_CPU

    cluster.run_for(MIN_AGE, runner=loop.execute)

    job = cluster.stored_job()
    assert job.status is JobStatus.QUEUED
    assert job.retry_count == 1
    assert job.assigned_node_id is None
    assert cluster.free_cpu() == CAPACITY - OTHER_CPU

    cluster.run_for(60, runner=loop.execute)

    assert cluster.stored_job().retry_count == 1
    assert cluster.free_cpu() == CAPACITY - OTHER_CPU


def test_without_the_new_step_the_job_stays_stranded() -> None:
    """
    The behaviour before ADR 0096: the same failure, the same loop
    with the step replaced by one that does nothing. The job is never
    reclaimed, however long the loop runs.
    """
    cluster = Cluster()
    loop = cluster.loop(sweep=NoSweep())

    cluster.jobs.fail_next_write = True
    loop.execute()
    cluster.run_for(MIN_AGE * 3, runner=loop.execute)

    assert cluster.stored_job().status is JobStatus.RUNNING
    assert cluster.leases.get_by_job_id(cluster.job_id, DEFAULT_TENANT_ID) is None
    assert cluster.free_cpu() == CAPACITY - JOB_CPU - OTHER_CPU


def test_a_crash_inside_an_outcome_report_does_not_credit_the_node_twice() -> None:
    """
    Reporting an outcome releases the lease, saves the worker and then
    saves the job. The job save is lost. The node was not credited yet
    (the job is saved first, ADR 0092), so recovery releases the main
    job's core once, and the node ends at capacity minus the job that
    is still running on it. Credited twice, it would show the other
    job's cores as free.
    """
    cluster = Cluster(main_lease_expired=False)
    report = ReportJobOutcomeService(
        worker_repository=cluster.workers,
        job_repository=cluster.jobs,
        node_repository=cluster.nodes,
        lease_repository=cluster.leases,
        release_lease_service=ReleaseLeaseService(
            lease_repository=cluster.leases,
            worker_repository=cluster.workers,
        ),
    )

    cluster.jobs.fail_write_of = cluster.job_id
    with pytest.raises(RuntimeError):
        report.complete(
            cluster.worker.id,
            cluster.job_id,
            cluster.worker.tenant_id,
            cluster.lease.id,
            exit_code=0,
        )

    assert cluster.leases.get_by_job_id(cluster.job_id, DEFAULT_TENANT_ID) is None
    assert cluster.stored_job().status is JobStatus.RUNNING
    assert cluster.free_cpu() == CAPACITY - JOB_CPU - OTHER_CPU

    cluster.service.execute()
    cluster.run_for(MIN_AGE)

    assert cluster.stored_job().status is JobStatus.QUEUED
    assert cluster.free_cpu() == CAPACITY - OTHER_CPU

    cluster.run_for(60)

    assert cluster.free_cpu() == CAPACITY - OTHER_CPU
    assert cluster.stored_job().retry_count == 1


# --- the time guard ---


def test_a_job_is_reclaimed_only_after_the_minimum_age() -> None:
    cluster = Cluster()
    cluster.lose_the_lease()

    cluster.service.execute()
    cluster.run_for(MIN_AGE - 10)

    assert cluster.stored_job().status is JobStatus.RUNNING
    assert cluster.free_cpu() == CAPACITY - JOB_CPU - OTHER_CPU

    cluster.run_for(10)

    assert cluster.stored_job().status is JobStatus.QUEUED


def test_a_reclaimed_job_frees_its_worker_and_leaves_other_workers() -> None:
    cluster = Cluster()
    cluster.lose_the_lease()

    cluster.service.execute()
    cluster.run_for(MIN_AGE)

    freed = cluster.stored_worker(cluster.worker)
    assert freed.is_idle()
    assert freed.running_job is None

    untouched = cluster.stored_worker(cluster.other_worker)
    assert untouched.running_job is not None
    assert untouched.running_job.id == cluster.other_id
    assert cluster.stored_job(cluster.other_id).status is JobStatus.RUNNING

    assert cluster.event_types() == ["JobReclaimed"]


def test_a_lease_that_returns_resets_the_clock() -> None:
    """
    The first sighting is not reused after the lease came back and
    went again: the age counts from the sighting that followed.
    """
    cluster = Cluster(min_age=100.0)
    live = Lease.create(
        worker_id=cluster.worker.id,
        job_id=cluster.job_id,
        tenant_id=cluster.worker.tenant_id,
    )
    cluster.lose_the_lease()

    cluster.service.execute()
    cluster.leases.save(live)
    cluster.run_for(10)
    cluster.lose_the_lease()
    cluster.run_for(10)

    cluster.run_for(80)

    assert cluster.stored_job().status is JobStatus.RUNNING

    cluster.run_for(20)

    assert cluster.stored_job().status is JobStatus.QUEUED


def test_a_pass_after_a_long_gap_does_not_confirm_an_old_sighting() -> None:
    """
    A process that stopped leading and started again must not join a
    sighting from before the gap to one after it.
    """
    cluster = Cluster(min_age=15.0, max_gap=30.0)
    cluster.lose_the_lease()

    cluster.service.execute()
    cluster.clock.advance(100)
    cluster.service.execute()

    assert cluster.stored_job().status is JobStatus.RUNNING

    cluster.run_for(10)
    assert cluster.stored_job().status is JobStatus.RUNNING

    cluster.run_for(10)
    assert cluster.stored_job().status is JobStatus.QUEUED


def test_a_pass_that_fails_to_read_clears_the_sightings() -> None:
    cluster = Cluster(min_age=15.0, max_gap=30.0)
    cluster.lose_the_lease()

    cluster.service.execute()
    cluster.clock.advance(10)

    cluster.leases.fail_listing = True
    with pytest.raises(RuntimeError):
        cluster.service.execute()
    cluster.leases.fail_listing = False

    cluster.clock.advance(10)
    cluster.service.execute()

    assert cluster.stored_job().status is JobStatus.RUNNING

    cluster.run_for(10)
    assert cluster.stored_job().status is JobStatus.RUNNING

    cluster.run_for(10)
    assert cluster.stored_job().status is JobStatus.QUEUED


def test_a_job_whose_status_changed_starts_its_clock_again() -> None:
    cluster = Cluster(min_age=15.0, max_gap=30.0)
    cluster.lose_the_lease()

    cluster.service.execute()

    job = cluster.stored_job()
    job.request_cancellation()
    cluster.jobs.save(job)

    cluster.run_for(10)
    cluster.run_for(10)

    assert cluster.stored_job().status is JobStatus.CANCELLING

    cluster.run_for(10)

    assert cluster.stored_job().status is JobStatus.CANCELLED


# --- the fence ---


def test_a_lease_that_appears_before_the_write_stops_the_reclaim() -> None:
    """
    A lease inserted after the service checked that none exists and
    before it writes. The fenced write sees it. No live lease ends up
    pointing at a QUEUED job, and the worker and node are untouched.
    """
    cluster = Cluster()
    cluster.lose_the_lease()
    cluster.service.execute()
    cluster.run_for(MIN_AGE - 10)

    cluster.leases.appears = Lease.create(
        worker_id=cluster.worker.id,
        job_id=cluster.job_id,
        tenant_id=cluster.worker.tenant_id,
    )
    cluster.run_for(10)

    assert cluster.stored_job().status is JobStatus.RUNNING
    assert (
        cluster.leases.get_by_job_id(cluster.job_id, DEFAULT_TENANT_ID)
        is not None
    )
    assert cluster.free_cpu() == CAPACITY - JOB_CPU - OTHER_CPU
    assert cluster.stored_worker(cluster.worker).running_job is not None
    assert cluster.event_types() == []


def test_a_status_saved_before_the_write_is_not_overwritten() -> None:
    """
    A late outcome report completes the job between the service's read
    and its write. The unconditional save the service used to make
    would have put the job back in the queue.
    """
    cluster = Cluster()
    cluster.lose_the_lease()
    cluster.service.execute()
    cluster.run_for(MIN_AGE - 10)

    def complete_the_job() -> None:
        job = cluster.stored_job()
        job.complete(exit_code=0)
        cluster.jobs.save(job)

    cluster.jobs.after_read = complete_the_job
    cluster.run_for(10)

    stored = cluster.stored_job()
    assert stored.status is JobStatus.COMPLETED
    assert stored.retry_count == 0
    assert cluster.free_cpu() == CAPACITY - JOB_CPU - OTHER_CPU
    assert cluster.stored_worker(cluster.worker).running_job is not None


# --- failures inside a reclaim ---


def test_a_lost_write_leaves_the_worker_and_the_job_together_and_is_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cluster = Cluster()
    cluster.lose_the_lease()
    cluster.service.execute()
    cluster.run_for(MIN_AGE - 10)

    cluster.jobs.fail_next_write = True
    with caplog.at_level("ERROR"):
        cluster.run_for(10)

    assert "the next pass tries again" in caplog.text
    assert cluster.stored_job().status is JobStatus.RUNNING
    assert cluster.stored_worker(cluster.worker).running_job is not None
    assert cluster.free_cpu() == CAPACITY - JOB_CPU - OTHER_CPU

    cluster.run_for(10)

    assert cluster.stored_job().status is JobStatus.QUEUED
    assert cluster.stored_worker(cluster.worker).is_idle()
    assert cluster.free_cpu() == CAPACITY - OTHER_CPU


def test_a_job_that_cannot_be_reclaimed_does_not_stop_the_others() -> None:
    cluster = Cluster()
    cluster.lose_the_lease()

    third = make_job(max_retries=3)
    third.queue()
    third.assign_to(cluster.node.id)
    node = cluster.nodes.get_by_id(cluster.node.id, DEFAULT_TENANT_ID)
    assert node is not None
    node.allocate(third.resources)
    cluster.nodes.save(node)
    cluster.jobs.save(third)

    cluster.service.execute()
    cluster.run_for(MIN_AGE - 10)

    cluster.jobs.fail_write_of = cluster.job_id
    cluster.run_for(10)

    assert cluster.stored_job(third.id).status is JobStatus.QUEUED
    assert cluster.stored_job().status is JobStatus.RUNNING
    assert cluster.stored_worker(cluster.worker).running_job is not None

    cluster.run_for(10)

    assert cluster.stored_job().status is JobStatus.QUEUED


def test_a_lost_event_does_not_make_the_job_a_suspect_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    The job is saved before its event. When the event is lost the job
    is already QUEUED, so it is not tried again, and the log says the
    event is lost rather than promising a retry.
    """
    cluster = Cluster(events=LosingEvents())
    cluster.lose_the_lease()
    cluster.service.execute()

    with caplog.at_level("ERROR"):
        cluster.run_for(MIN_AGE)

    assert cluster.stored_job().status is JobStatus.QUEUED
    assert cluster.stored_worker(cluster.worker).is_idle()
    assert "its event was not recorded" in caplog.text
    assert "will not be retried" in caplog.text
    assert "tries again" not in caplog.text

    cluster.run_for(60)

    assert cluster.stored_job().retry_count == 1
    assert cluster.free_cpu() == CAPACITY - OTHER_CPU


# --- the other states, retries and ordinary jobs ---


def test_a_job_with_a_live_lease_is_never_reclaimed() -> None:
    cluster = Cluster(main_lease_expired=False)

    cluster.service.execute()
    cluster.run_for(MIN_AGE * 3)

    assert cluster.stored_job().status is JobStatus.RUNNING
    assert cluster.free_cpu() == CAPACITY - JOB_CPU - OTHER_CPU


def test_a_job_that_finished_before_the_age_is_left_alone() -> None:
    cluster = Cluster()
    cluster.lose_the_lease()
    cluster.service.execute()

    job = cluster.stored_job()
    job.complete(exit_code=0)
    cluster.jobs.save(job)

    cluster.run_for(MIN_AGE)

    stored = cluster.stored_job()
    assert stored.status is JobStatus.COMPLETED
    assert stored.retry_count == 0


def test_a_queued_job_has_no_lease_and_is_not_touched() -> None:
    cluster = Cluster()
    job = cluster.stored_job()
    job.reclaim()
    cluster.jobs.save(job)
    cluster.lose_the_lease()

    cluster.service.execute()
    cluster.run_for(MIN_AGE * 2)

    stored = cluster.stored_job()
    assert stored.status is JobStatus.QUEUED
    assert stored.retry_count == 1


def test_a_job_out_of_retries_fails_instead_of_requeuing() -> None:
    cluster = Cluster(max_retries=0)
    cluster.lose_the_lease()

    cluster.service.execute()
    cluster.run_for(MIN_AGE)

    assert cluster.stored_job().status is JobStatus.FAILED
    assert cluster.free_cpu() == CAPACITY - OTHER_CPU


def test_a_cancelling_job_without_a_lease_is_cancelled_not_retried() -> None:
    cluster = Cluster()
    job = cluster.stored_job()
    job.request_cancellation()
    cluster.jobs.save(job)
    cluster.lose_the_lease()

    cluster.service.execute()
    cluster.run_for(MIN_AGE)

    stored = cluster.stored_job()
    assert stored.status is JobStatus.CANCELLED
    assert stored.retry_count == 0
    assert cluster.free_cpu() == CAPACITY - OTHER_CPU
    assert cluster.event_types() == ["JobCancelled"]
