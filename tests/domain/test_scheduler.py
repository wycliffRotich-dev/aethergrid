from app.domain.entities.job import Job
from app.domain.services.scheduler import Scheduler
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from tests.support.nodes import make_node


def test_scheduler_selects_node_with_sufficient_resources() -> None:
    scheduler = Scheduler()

    node = make_node(
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

    selected = scheduler.select_node(
        job,
        [node],
    )

    assert selected == node


def test_scheduler_returns_none_when_no_node_matches() -> None:
    scheduler = Scheduler()

    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=2,
            memory_mib=2048,
            vram_mib=0,
        ),
    )

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=8192,
        ),
    )

    selected = scheduler.select_node(
        job,
        [node],
    )

    assert selected is None
