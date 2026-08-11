from app.application.services.cluster_tick_service import (
    ClusterTickService,
)
from app.domain.entities.job import Job
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.enums.worker_management import WorkerManagement
from app.domain.enums.worker_status import WorkerStatus
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)


class FakeSchedulerLoopService:
    """
    No-op stand-in. These tests exercise ClusterTickService's own
    worker-driving logic, not scheduling, so scheduling behavior is
    deliberately out of scope here.
    """

    def execute(self) -> None:
        pass


class FakeWorkerExecutionLoop:
    """
    Records which worker IDs it was asked to drive, instead of
    actually executing anything. Lets the test assert on exactly
    what ClusterTickService chose to act on.
    """

    def __init__(self) -> None:
        self.executed_worker_ids: list[WorkerId] = []

    def execute(self, worker_id: WorkerId) -> None:
        self.executed_worker_ids.append(worker_id)


def _make_worker_with_running_job(
    managed_by: WorkerManagement,
) -> Worker:
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )
    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=2,
            memory_mib=2048,
            vram_mib=0,
        ),
    )
    return Worker(
        id=WorkerId.new(),
        node=node,
        status=WorkerStatus.BUSY,
        managed_by=managed_by,
        running_job=job,
    )


def test_execute_drives_dashboard_managed_worker_with_running_job() -> (
    None
):
    worker = _make_worker_with_running_job(
        managed_by=WorkerManagement.DASHBOARD,
    )
    repository = InMemoryWorkerRepository([worker])
    worker_execution_loop = FakeWorkerExecutionLoop()

    service = ClusterTickService(
        scheduler_loop_service=FakeSchedulerLoopService(),
        worker_execution_loop=worker_execution_loop,
        worker_repository=repository,
    )

    service.execute()

    assert worker_execution_loop.executed_worker_ids == [worker.id]


def test_execute_skips_agent_managed_worker_with_running_job() -> None:
    """
    The actual fix for issue #90: a worker whose jobs are owned by
    a standalone agent (scripts/run_agent.py, ADR 0019) must never
    be driven by the in-process loop too, or the two race for the
    same job.
    """
    worker = _make_worker_with_running_job(
        managed_by=WorkerManagement.AGENT,
    )
    repository = InMemoryWorkerRepository([worker])
    worker_execution_loop = FakeWorkerExecutionLoop()

    service = ClusterTickService(
        scheduler_loop_service=FakeSchedulerLoopService(),
        worker_execution_loop=worker_execution_loop,
        worker_repository=repository,
    )

    service.execute()

    assert worker_execution_loop.executed_worker_ids == []


def test_execute_drives_dashboard_worker_and_skips_agent_worker_together() -> (
    None
):
    """
    Both kinds of worker coexisting in the same tick, since that's
    the actual state of a cluster mid-migration to agents: some
    workers still dashboard-managed, some already agent-managed.
    """
    dashboard_worker = _make_worker_with_running_job(
        managed_by=WorkerManagement.DASHBOARD,
    )
    agent_worker = _make_worker_with_running_job(
        managed_by=WorkerManagement.AGENT,
    )
    repository = InMemoryWorkerRepository(
        [dashboard_worker, agent_worker],
    )
    worker_execution_loop = FakeWorkerExecutionLoop()

    service = ClusterTickService(
        scheduler_loop_service=FakeSchedulerLoopService(),
        worker_execution_loop=worker_execution_loop,
        worker_repository=repository,
    )

    service.execute()

    assert worker_execution_loop.executed_worker_ids == [
        dashboard_worker.id,
    ]
