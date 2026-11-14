"""ADR 0096: a job left without a lease is reclaimed, on Postgres.

Expired-lease recovery deletes the lease row in one write and saves the
job in another. A failed job save between them leaves a RUNNING job
that no lease row points at. The pass that follows lists leases and no
longer sees it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import pytest
from psycopg_pool import ConnectionPool

from app.application.reconciliation.reconciliation_loop import (
    ReconciliationLoop,
)
from app.application.reconciliation.recover_expired_lease_service import (
    RecoverExpiredLeaseService,
)
from app.application.reconciliation.recover_leaseless_job_service import (
    MIN_LEASELESS_AGE_SECONDS,
    RecoverLeaselessJobService,
)
from app.application.reconciliation.recover_offline_node_service import (
    RecoverOfflineNodeService,
)
from app.application.services.cancel_job_service import CancelJobService
from app.application.services.mark_dead_workers_service import (
    MarkDeadWorkersService,
)
from app.application.services.release_lease_service import (
    ReleaseLeaseService,
)
from app.application.services.report_job_outcome_service import (
    ReportJobOutcomeService,
)
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.node import Node
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.entities.worker import Worker
from app.domain.enums.job_status import JobStatus
from app.domain.exceptions.job_reclaimed_error import JobReclaimedError
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.postgres_job_repository import (
    PostgresJobRepository,
)
from app.infrastructure.repositories.postgres_lease_repository import (
    PostgresLeaseRepository,
)
from app.infrastructure.repositories.postgres_node_repository import (
    PostgresNodeRepository,
)
from app.infrastructure.repositories.postgres_worker_repository import (
    PostgresWorkerRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node
from tests.support.workers import make_worker

CAPACITY = 8
JOB_CPU = 1
OTHER_CPU = 2
MIN_AGE = MIN_LEASELESS_AGE_SECONDS


@pytest.fixture
def pool(test_database_url: str):
    test_pool = ConnectionPool(
        test_database_url,
        min_size=1,
        max_size=5,
        open=True,
        kwargs={"autocommit": True},
    )
    with test_pool.connection() as conn:
        conn.execute("TRUNCATE leases, workers, jobs, nodes CASCADE")
    yield test_pool
    test_pool.close()


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class LosingJobRepository(PostgresJobRepository):
    """
    Loses one write, the way a dropped connection or a killed process
    does after the lease row is already gone. Can also run a hook once,
    before a fenced write, to stand for a caller that stalls there.
    """

    fail_next_write = False
    before_fenced_write: Callable[[], None] | None = None

    def save(self, job: Job) -> None:
        if self.fail_next_write:
            self.fail_next_write = False
            raise RuntimeError("the write was lost")

        super().save(job)

    def save_if_leaseless(
        self,
        job: Job,
        expected_statuses: frozenset[JobStatus],
    ) -> bool:
        if self.before_fenced_write is not None:
            hook, self.before_fenced_write = self.before_fenced_write, None
            hook()

        if self.fail_next_write:
            self.fail_next_write = False
            raise RuntimeError("the write was lost")

        return super().save_if_leaseless(job, expected_statuses)


class LeaseFromAnotherConnection(PostgresLeaseRepository):
    """
    Inserts a live lease, through another pooled connection, at the
    exact point between the service's check that none exists and its
    write.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        super().__init__(pool)
        self.appears: Lease | None = None

    def get_by_job_id(self, job_id, tenant_id):  # type: ignore[no-untyped-def]
        found = super().get_by_job_id(job_id, tenant_id)

        if found is None and self.appears is not None:
            lease, self.appears = self.appears, None
            self.save(lease)

        return found


class Fleet:
    """One node, a running job with an expired lease, and another
    running job holding two cores under a live lease."""

    def __init__(
        self,
        pool: ConnectionPool,
        *,
        main_lease_expired: bool = True,
    ) -> None:
        self.pool = pool
        self.clock = Clock()
        self.node: Node = make_node(tenant_id=DEFAULT_TENANT_ID)
        self.node.capacity = ResourceRequirements(
            cpu_cores=CAPACITY, memory_mib=16384, vram_mib=0
        )
        self.node.available = self.node.capacity

        self.job: Job = make_job(
            max_retries=3,
            resources=ResourceRequirements(
                cpu_cores=JOB_CPU, memory_mib=512, vram_mib=0
            ),
        )
        self.job.queue()
        self.job.assign_to(self.node.id)
        self.node.allocate(self.job.resources)

        self.other: Job = make_job(
            max_retries=3,
            resources=ResourceRequirements(
                cpu_cores=OTHER_CPU, memory_mib=1024, vram_mib=0
            ),
        )
        self.other.queue()
        self.other.assign_to(self.node.id)
        self.node.allocate(self.other.resources)

        self.worker: Worker = make_worker(node=self.node)
        self.worker.ready()
        self.worker.accept(self.job)
        self.worker.start()

        self.other_worker: Worker = make_worker(node=self.node)
        self.other_worker.ready()
        self.other_worker.accept(self.other)
        self.other_worker.start()

        self.jobs = LosingJobRepository(pool)
        self.leases = LeaseFromAnotherConnection(pool)
        self.workers = PostgresWorkerRepository(pool)
        self.nodes = PostgresNodeRepository(pool)

        self.nodes.save(self.node)
        self.jobs.save(self.job)
        self.jobs.save(self.other)
        self.workers.save(self.worker)
        self.workers.save(self.other_worker)

        self.lease = Lease.create(
            worker_id=self.worker.id,
            job_id=self.job.id,
            tenant_id=self.worker.tenant_id,
            duration=(
                timedelta(seconds=-1)
                if main_lease_expired
                else timedelta(hours=1)
            ),
        )
        self.leases.save(self.lease)
        self.leases.save(
            Lease.create(
                worker_id=self.other_worker.id,
                job_id=self.other.id,
                tenant_id=self.other_worker.tenant_id,
                duration=timedelta(hours=1),
            )
        )

        self.service = RecoverLeaselessJobService(
            job_repository=self.jobs,
            lease_repository=self.leases,
            worker_repository=self.workers,
            node_repository=self.nodes,
            clock=self.clock,
        )

    def stored_job(self) -> Job:
        job = self.jobs.get_by_id(self.job.id, DEFAULT_TENANT_ID)
        assert job is not None
        return job

    def free_cpu(self) -> int:
        node = self.nodes.get_by_id(self.node.id, DEFAULT_TENANT_ID)
        assert node is not None
        return node.available.cpu_cores

    def report(self) -> ReportJobOutcomeService:
        return ReportJobOutcomeService(
            worker_repository=self.workers,
            job_repository=self.jobs,
            node_repository=self.nodes,
            lease_repository=self.leases,
            release_lease_service=ReleaseLeaseService(
                lease_repository=self.leases,
                worker_repository=self.workers,
            ),
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
            recover_leaseless_job_service=self.service,
        )

    def run_for(self, seconds: float, runner=None) -> None:  # type: ignore[no-untyped-def]
        run = runner or self.service.execute
        elapsed = 0.0
        while elapsed < seconds:
            self.clock.advance(10.0)
            run()
            elapsed += 10.0


def test_a_job_stranded_by_a_failed_save_is_requeued_and_its_node_freed(
    pool: ConnectionPool,
) -> None:
    fleet = Fleet(pool)
    loop = fleet.loop()

    fleet.jobs.fail_next_write = True
    loop.execute()

    stranded = fleet.stored_job()
    assert stranded.status is JobStatus.RUNNING
    assert fleet.leases.get_by_job_id(fleet.job.id, DEFAULT_TENANT_ID) is None
    assert fleet.free_cpu() == CAPACITY - JOB_CPU - OTHER_CPU

    fleet.run_for(MIN_AGE, runner=loop.execute)

    recovered = fleet.stored_job()
    assert recovered.status is JobStatus.QUEUED
    assert recovered.retry_count == 1
    assert recovered.assigned_node_id is None

    assert fleet.free_cpu() == CAPACITY - OTHER_CPU

    stored_worker = fleet.workers.get_by_id(
        fleet.worker.id, fleet.worker.tenant_id
    )
    assert stored_worker is not None
    assert stored_worker.is_idle()

    fleet.run_for(60, runner=loop.execute)

    assert fleet.free_cpu() == CAPACITY - OTHER_CPU
    assert fleet.stored_job().retry_count == 1


def test_a_lease_inserted_before_the_write_stops_the_reclaim(
    pool: ConnectionPool,
) -> None:
    """
    Two connections: the lease is inserted by another one between the
    service's check and its write. No live lease may end up pointing at
    a QUEUED job.
    """
    fleet = Fleet(pool)
    fleet.leases.delete(fleet.job.id, DEFAULT_TENANT_ID)
    fleet.service.execute()
    fleet.run_for(MIN_AGE - 10)

    fleet.leases.appears = Lease.create(
        worker_id=fleet.worker.id,
        job_id=fleet.job.id,
        tenant_id=fleet.worker.tenant_id,
    )
    fleet.run_for(10)

    assert fleet.stored_job().status is JobStatus.RUNNING
    assert (
        fleet.leases.get_by_job_id(fleet.job.id, DEFAULT_TENANT_ID)
        is not None
    )
    assert fleet.free_cpu() == CAPACITY - JOB_CPU - OTHER_CPU

    with pool.connection() as conn:
        queued_with_a_lease = conn.execute(
            "SELECT count(*) FROM leases l JOIN jobs j ON j.id = l.job_id "
            "WHERE j.status = 'QUEUED'"
        ).fetchone()
    assert queued_with_a_lease is not None
    assert queued_with_a_lease[0] == 0


def test_a_crash_inside_an_outcome_report_does_not_credit_the_node_twice(
    pool: ConnectionPool,
) -> None:
    """
    The report path on a real database: the job save is lost after the
    lease is released and the worker is saved. The node is credited
    only after the job is saved, so recovery credits the main job's
    core once. The other job's two cores stay allocated.
    """
    fleet = Fleet(pool, main_lease_expired=False)
    report = ReportJobOutcomeService(
        worker_repository=fleet.workers,
        job_repository=fleet.jobs,
        node_repository=fleet.nodes,
        lease_repository=fleet.leases,
        release_lease_service=ReleaseLeaseService(
            lease_repository=fleet.leases,
            worker_repository=fleet.workers,
        ),
    )

    fleet.jobs.fail_next_write = True
    with pytest.raises(RuntimeError):
        report.complete(
            fleet.worker.id,
            fleet.job.id,
            fleet.worker.tenant_id,
            fleet.lease.id,
            exit_code=0,
        )

    assert fleet.stored_job().status is JobStatus.RUNNING
    assert fleet.free_cpu() == CAPACITY - JOB_CPU - OTHER_CPU

    fleet.service.execute()
    fleet.run_for(MIN_AGE)

    assert fleet.stored_job().status is JobStatus.QUEUED
    assert fleet.free_cpu() == CAPACITY - OTHER_CPU

    fleet.run_for(60)

    assert fleet.free_cpu() == CAPACITY - OTHER_CPU


def test_an_outcome_report_that_stalls_past_the_reclaim_is_refused(
    pool: ConnectionPool,
) -> None:
    """
    The report releases the lease and saves the worker, then stalls
    before the job save while the sweep reclaims the job and credits
    its core. The report's fenced write is refused on the real
    database: the job stays QUEUED and the core is credited once.
    """
    fleet = Fleet(pool, main_lease_expired=False)

    def stall() -> None:
        fleet.service.execute()
        fleet.run_for(MIN_AGE)

    fleet.jobs.before_fenced_write = stall

    with pytest.raises(JobReclaimedError):
        fleet.report().complete(
            fleet.worker.id,
            fleet.job.id,
            fleet.worker.tenant_id,
            fleet.lease.id,
            exit_code=0,
        )

    stored = fleet.stored_job()
    assert stored.status is JobStatus.QUEUED
    assert stored.retry_count == 1
    assert fleet.free_cpu() == CAPACITY - OTHER_CPU

    fleet.run_for(60)

    assert fleet.stored_job().status is JobStatus.QUEUED
    assert fleet.free_cpu() == CAPACITY - OTHER_CPU


def test_an_outcome_report_still_wins_over_a_cancel_request_saved_during_it(
    pool: ConnectionPool,
) -> None:
    fleet = Fleet(pool, main_lease_expired=False)

    def cancel() -> None:
        CancelJobService(job_repository=fleet.jobs).execute(
            fleet.job.id,
            DEFAULT_TENANT_ID,
        )
        assert fleet.stored_job().status is JobStatus.CANCELLING

    fleet.jobs.before_fenced_write = cancel

    fleet.report().complete(
        fleet.worker.id,
        fleet.job.id,
        fleet.worker.tenant_id,
        fleet.lease.id,
        exit_code=0,
    )

    assert fleet.stored_job().status is JobStatus.COMPLETED
    assert fleet.free_cpu() == CAPACITY - OTHER_CPU

    fleet.service.execute()
    fleet.run_for(MIN_AGE * 2)

    assert fleet.stored_job().status is JobStatus.COMPLETED
    assert fleet.free_cpu() == CAPACITY - OTHER_CPU


def test_a_running_job_with_a_live_lease_is_left_alone(
    pool: ConnectionPool,
) -> None:
    fleet = Fleet(pool, main_lease_expired=False)

    fleet.service.execute()
    fleet.run_for(MIN_AGE * 2)

    assert fleet.stored_job().status is JobStatus.RUNNING
    assert fleet.free_cpu() == CAPACITY - JOB_CPU - OTHER_CPU
