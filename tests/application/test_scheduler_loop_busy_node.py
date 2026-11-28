"""A node that refuses a job must not hold that job back from other nodes.

One node has one worker (ADR 0030). Best fit (ADR 0043) picks the node
with the least room left, which is often a node whose only worker is
already busy. AssignWorkerService then refuses the job, and the loop
puts it back in the queue (ADR 0027). These tests check that the loop
then asks the Scheduler again without that node, in the same tick, so
an idle node gets the job.
"""

from __future__ import annotations

from app.application.services.assign_worker_service import (
    AssignWorkerService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.application.services.scheduler_loop_service import (
    SchedulerLoopService,
)
from app.domain.entities.job import Job
from app.domain.entities.node import Node
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.entities.worker import Worker
from app.domain.enums.job_status import JobStatus
from app.domain.enums.worker_status import WorkerStatus
from app.domain.services.scheduler import Scheduler
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
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

TWO_CORES = ResourceRequirements(cpu_cores=2, memory_mib=2048, vram_mib=0)


def _queued_job() -> Job:
    job = make_job(resources=TWO_CORES)
    job.queue()
    return job


def _loop(
    jobs: list[Job],
    nodes: list[Node],
    workers: list[Worker],
) -> tuple[SchedulerLoopService, InMemoryWorkerRepository, InMemoryEventRepository]:
    worker_repository = InMemoryWorkerRepository(workers)
    event_repository = InMemoryEventRepository()
    loop = SchedulerLoopService(
        InMemoryJobRepository(jobs),
        InMemoryNodeRepository(nodes),
        Scheduler(),
        assign_worker_service=AssignWorkerService(
            worker_repository=worker_repository,
        ),
        record_job_events_service=RecordJobEventsService(
            event_repository=event_repository,
        ),
    )
    return loop, worker_repository, event_repository


def test_a_job_goes_to_an_idle_node_when_the_best_fit_node_is_busy() -> None:
    busy_node = make_node()
    idle_node = make_node()
    running = make_job(resources=TWO_CORES)
    running.queue()
    running.assign_to(busy_node.id)
    busy_node.allocate(running.resources)
    busy_worker = make_worker(node=busy_node, status=WorkerStatus.IDLE)
    busy_worker.accept(running)
    idle_worker = make_worker(node=idle_node, status=WorkerStatus.IDLE)
    job = _queued_job()
    loop, _, _ = _loop([running, job], [busy_node, idle_node], [busy_worker, idle_worker])
    assert Scheduler().select_node(job, [busy_node, idle_node]) is busy_node

    loop.execute()

    assert job.status is JobStatus.SCHEDULED
    assert job.assigned_node_id == idle_node.id
    assert idle_worker.status is WorkerStatus.BUSY
    assert idle_worker.running_job is job


def test_two_jobs_on_two_idle_nodes_both_start_in_one_tick() -> None:
    node_a = make_node()
    node_b = make_node()
    worker_a = make_worker(node=node_a, status=WorkerStatus.IDLE)
    worker_b = make_worker(node=node_b, status=WorkerStatus.IDLE)
    first = _queued_job()
    second = _queued_job()
    loop, _, _ = _loop([first, second], [node_a, node_b], [worker_a, worker_b])

    loop.execute()

    assert first.status is JobStatus.SCHEDULED
    assert second.status is JobStatus.SCHEDULED
    assert {first.assigned_node_id, second.assigned_node_id} == {node_a.id, node_b.id}
    assert worker_a.status is WorkerStatus.BUSY
    assert worker_b.status is WorkerStatus.BUSY


def test_the_refused_node_gets_its_capacity_back() -> None:
    busy_node = make_node()
    idle_node = make_node()
    running = make_job(resources=TWO_CORES)
    running.queue()
    running.assign_to(busy_node.id)
    busy_node.allocate(running.resources)
    busy_worker = make_worker(node=busy_node, status=WorkerStatus.IDLE)
    busy_worker.accept(running)
    idle_worker = make_worker(node=idle_node, status=WorkerStatus.IDLE)
    job = _queued_job()
    available_before = busy_node.available
    loop, _, _ = _loop([running, job], [busy_node, idle_node], [busy_worker, idle_worker])

    loop.execute()

    assert busy_node.available == available_before


def test_a_job_with_no_idle_worker_anywhere_tries_each_node_once() -> None:
    nodes = [make_node(), make_node(), make_node()]
    workers = [make_worker(node=node, status=WorkerStatus.BUSY) for node in nodes]
    capacity_before = [node.available for node in nodes]
    job = _queued_job()
    loop, _, events = _loop([job], nodes, workers)

    loop.execute()

    assert job.status is JobStatus.QUEUED
    assert job.assigned_node_id is None
    assert [node.available for node in nodes] == capacity_before
    types = [event.event_type for event in events.list(DEFAULT_TENANT_ID)]
    assert types == ["JobScheduled", "JobUnscheduled"] * len(nodes)


def test_a_node_that_refused_is_not_offered_again_in_the_same_tick() -> None:
    busy_node = make_node()
    busy_worker = make_worker(node=busy_node, status=WorkerStatus.BUSY)
    jobs = [_queued_job(), _queued_job()]
    loop, _, events = _loop(jobs, [busy_node], [busy_worker])

    loop.execute()

    assert all(job.status is JobStatus.QUEUED for job in jobs)
    types = [event.event_type for event in events.list(DEFAULT_TENANT_ID)]
    assert types == ["JobScheduled", "JobUnscheduled"]
