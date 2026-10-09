from app.application.services.scheduler_loop_service import (
    SchedulerLoopService,
)
from app.domain.enums.job_status import JobStatus
from app.domain.services.scheduler import Scheduler
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node


def test_scheduler_loop_schedules_highest_priority_job_first() -> None:
    """
    Queued jobs should be scheduled in
    descending priority order.
    """

    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=1,
            memory_mib=1024,
            vram_mib=0,
        ),
    )

    low = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
        priority=1,
    )

    medium = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
        priority=5,
    )

    high = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
        priority=10,
    )

    low.queue()
    medium.queue()
    high.queue()

    job_repository = InMemoryJobRepository(
        [
            low,
            medium,
            high,
        ],
    )

    node_repository = InMemoryNodeRepository(
        [
            node,
        ],
    )

    service = SchedulerLoopService(
        job_repository,
        node_repository,
        Scheduler(),
    )

    service.execute()

    assert high.status == JobStatus.SCHEDULED
    assert high.assigned_node_id == node.id

    assert medium.status == JobStatus.QUEUED
    assert low.status == JobStatus.QUEUED
