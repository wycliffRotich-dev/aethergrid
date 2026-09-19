from __future__ import annotations

from datetime import timedelta

from app.domain.entities.job import Job
from app.domain.entities.node import Node
from app.domain.entities.worker import (
    HEARTBEAT_TIMEOUT,
    Worker,
    utc_now,
)
from app.domain.enums.worker_status import WorkerStatus
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.worker_id import WorkerId


def create_worker() -> Worker:
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=8192,
        ),
    )

    return Worker(
        id=WorkerId.new(),
        node=node,
    )


def test_worker_is_alive_by_default() -> None:
    worker = create_worker()

    assert worker.is_alive()


def test_worker_becomes_offline_after_heartbeat_timeout() -> None:
    worker = create_worker()

    worker.last_seen_at = (
        utc_now()
        - HEARTBEAT_TIMEOUT
        - timedelta(seconds=1)
    )

    assert not worker.is_alive()


def test_offline_transitions_worker_to_offline_status() -> None:
    worker = create_worker()

    worker.offline()

    assert worker.status is WorkerStatus.OFFLINE


def test_heartbeat_recovers_offline_worker_with_no_running_job() -> None:
    """
    ADR 0041: a worker that went OFFLINE while genuinely idle, no
    running_job attached, must return to IDLE the moment a heartbeat
    arrives. This is the real gap: before this behavior existed, a
    worker in this exact state (observed live -- a dashboard tab's
    heartbeat keeper going idle overnight) had no path back to IDLE
    at all.
    """
    worker = create_worker()
    worker.offline()

    assert worker.status is WorkerStatus.OFFLINE
    assert worker.running_job is None

    worker.heartbeat()

    assert worker.status is WorkerStatus.IDLE


def test_heartbeat_does_not_recover_offline_worker_with_running_job() -> None:
    """
    ADR 0041's actual guard: an OFFLINE worker that still holds a
    running_job must NOT be recovered by a bare heartbeat.
    RecoverOfflineNodeService may already be reassigning that exact
    job to a different worker by the time a late heartbeat from this
    worker arrives; recovering status here would let this worker
    believe it can accept new work while a stale job reference still
    needs resolving by reconciliation first.
    """
    worker = create_worker()

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=1024,
            vram_mib=0,
        ),
    )
    job.queue()
    job.assign_to(worker.node.id)

    worker.ready()
    worker.accept(job)
    worker.offline()

    assert worker.status is WorkerStatus.OFFLINE
    assert worker.running_job is not None

    worker.heartbeat()

    assert worker.status is WorkerStatus.OFFLINE
