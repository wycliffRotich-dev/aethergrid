from app.domain.entities.job import Job
from app.domain.services.scheduler import Scheduler
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from tests.support.nodes import make_node


def test_scheduler_requires_all_constraints() -> None:
    """
    A node must satisfy every job constraint
    to be considered for scheduling.
    """

    europe = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=8192,
        ),
    )
    europe.labels["gpu"] = "true"
    europe.labels["region"] = "eu-west"

    wrong_region = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=8192,
        ),
    )
    wrong_region.labels["gpu"] = "true"
    wrong_region.labels["region"] = "us-east"

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=2,
            memory_mib=2048,
            vram_mib=1024,
        ),
    )
    job.constraints["gpu"] = "true"
    job.constraints["region"] = "eu-west"

    scheduler = Scheduler()

    selected = scheduler.select_node(
        job,
        [
            wrong_region,
            europe,
        ],
    )

    assert selected == europe
