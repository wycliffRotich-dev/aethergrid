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
from app.domain.entities.worker import Worker
from app.domain.enums.job_status import JobStatus
from app.domain.enums.worker_status import WorkerStatus
from app.domain.services.scheduler import Scheduler
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


def test_scheduler_loop_schedules_queued_jobs() -> None:
    """
    Queued jobs should automatically be scheduled
    onto healthy compute nodes.
    """
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=16384,
        ),
    )
    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=4096,
            vram_mib=2048,
        ),
    )
    job.queue()
    jobs = InMemoryJobRepository([job])
    nodes = InMemoryNodeRepository([node])
    service = SchedulerLoopService(
        jobs,
        nodes,
        Scheduler(),
    )
    service.execute()
    assert job.status == JobStatus.SCHEDULED
    assert job.assigned_node_id == node.id


def test_scheduler_loop_assigns_idle_worker_and_starts_job() -> None:
    """
    When an idle worker exists on the selected node, a
    single tick must both schedule the job onto the node
    and hand it to that worker, moving the worker to BUSY
    and attaching the job as its running_job. The job itself
    stays SCHEDULED, not RUNNING: assignment means the worker
    now holds the job, not that execution has begun. A job
    only transitions to RUNNING once whatever is actually
    executing it confirms it has started (see ADR 0019) --
    reporting RUNNING any earlier would be the system lying
    about its own state. This is the full pipeline that
    CreateJobService used to only get half of (node
    allocation, with no worker assignment); it must be
    covered here since SchedulerLoopService is now the single
    place scheduling and assignment both happen.
    """
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=16384,
        ),
    )

    worker = Worker(
        id=WorkerId.new(),
        node=node,
        status=WorkerStatus.IDLE,
    )

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=4096,
            vram_mib=2048,
        ),
    )
    job.queue()

    jobs = InMemoryJobRepository([job])
    nodes = InMemoryNodeRepository([node])
    workers = InMemoryWorkerRepository([worker])

    assign_worker_service = AssignWorkerService(
        worker_repository=workers,
    )

    service = SchedulerLoopService(
        jobs,
        nodes,
        Scheduler(),
        assign_worker_service=assign_worker_service,
    )

    service.execute()

    assert job.status == JobStatus.SCHEDULED
    assert job.assigned_node_id == node.id

    stored_worker = workers.get_by_id(worker.id)
    assert stored_worker is not None
    assert stored_worker.status == WorkerStatus.BUSY
    assert stored_worker.running_job is job
def test_scheduler_loop_records_job_scheduled_event() -> None:
    """
    Scheduling a job onto a node must record a JobScheduled
    event, the same way CreateJobService already records
    JobCreated -- the event history should reflect the job's
    real lifecycle, not just its creation.
    """
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=16384,
        ),
    )

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=4096,
            vram_mib=2048,
        ),
    )
    job.queue()

    jobs = InMemoryJobRepository([job])
    nodes = InMemoryNodeRepository([node])
    events = InMemoryEventRepository()

    record_job_events_service = RecordJobEventsService(
        event_repository=events,
    )

    service = SchedulerLoopService(
        jobs,
        nodes,
        Scheduler(),
        record_job_events_service=record_job_events_service,
    )

    service.execute()

    recorded = events.list()

    assert len(recorded) == 1
    assert recorded[0].event_type == "JobScheduled"
    assert recorded[0].aggregate_id == str(job.id)
    assert recorded[0].aggregate_type == "Job"
