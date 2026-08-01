from datetime import UTC, datetime, timedelta

from app.application.reconciliation.recover_offline_node_service import (
    RecoverOfflineNodeService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.job import Job
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.worker_id import WorkerId
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


def _make_offline_node() -> Node:
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )
    node.last_seen_at = datetime.now(UTC) - timedelta(minutes=2)
    return node


def test_recover_offline_node_requeues_job_with_retries_remaining() -> None:
    """
    A job assigned to a worker on an offline node, with
    retry budget remaining, is reclaimed back to QUEUED.
    """
    node = _make_offline_node()

    worker = Worker(
        id=WorkerId.new(),
        node=node,
    )

    worker.ready()

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
        max_retries=1,
    )

    job.queue()
    job.assign_to(node.id)

    worker.accept(job)
    worker.start()

    node_repository = InMemoryNodeRepository([node])
    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])

    service = RecoverOfflineNodeService(
        node_repository=node_repository,
        worker_repository=worker_repository,
        job_repository=job_repository,
    )

    service.execute()

    recovered_worker = worker_repository.get_by_id(worker.id)
    recovered_job = job_repository.get_by_id(job.id)

    assert recovered_worker is not None
    assert recovered_worker.is_idle()

    assert recovered_job is not None
    assert recovered_job.is_queued()
    assert recovered_job.retry_count == 1


def test_recover_offline_node_fails_job_once_retries_exhausted() -> None:
    """
    A job with no retry budget remaining is failed outright
    when its node goes offline, rather than requeued onto a
    fleet that may reassign it right back to the same
    unhealthy node.
    """
    node = _make_offline_node()

    worker = Worker(
        id=WorkerId.new(),
        node=node,
    )

    worker.ready()

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
        max_retries=0,
    )

    job.queue()
    job.assign_to(node.id)

    worker.accept(job)
    worker.start()

    node_repository = InMemoryNodeRepository([node])
    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])

    service = RecoverOfflineNodeService(
        node_repository=node_repository,
        worker_repository=worker_repository,
        job_repository=job_repository,
    )

    service.execute()

    recovered_worker = worker_repository.get_by_id(worker.id)
    recovered_job = job_repository.get_by_id(job.id)

    assert recovered_worker is not None
    assert recovered_worker.is_idle()

    assert recovered_job is not None
    assert recovered_job.is_failed()
def test_recover_offline_node_records_job_reclaimed_event() -> None:
    """
    Reclaiming a job assigned to an offline node must
    record a JobReclaimed event.
    """
    node = _make_offline_node()

    worker = Worker(
        id=WorkerId.new(),
        node=node,
    )

    worker.ready()

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
        max_retries=1,
    )

    job.queue()
    job.assign_to(node.id)

    worker.accept(job)
    worker.start()

    node_repository = InMemoryNodeRepository([node])
    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])

    events = InMemoryEventRepository()
    record_job_events_service = RecordJobEventsService(
        event_repository=events,
    )

    service = RecoverOfflineNodeService(
        node_repository=node_repository,
        worker_repository=worker_repository,
        job_repository=job_repository,
        record_job_events_service=record_job_events_service,
    )

    service.execute()

    recorded = events.list()

    assert len(recorded) == 1
    assert recorded[0].event_type == "JobReclaimed"
    assert recorded[0].aggregate_id == str(job.id)
    assert recorded[0].aggregate_type == "Job"
