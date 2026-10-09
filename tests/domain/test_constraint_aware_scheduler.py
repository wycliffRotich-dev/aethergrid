from app.domain.services.scheduler import Scheduler
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node


def test_scheduler_respects_job_constraints() -> None:
    """
    Scheduler should ignore nodes that do not
    satisfy a job's constraints.
    """

    gpu_node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=8192,
        ),
    )
    gpu_node.labels["gpu"] = "true"

    cpu_node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=8192,
        ),
    )
    cpu_node.labels["gpu"] = "false"

    job = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=2,
            memory_mib=2048,
            vram_mib=1024,
        ),
    )
    job.constraints["gpu"] = "true"

    scheduler = Scheduler()

    selected = scheduler.select_node(
        job,
        [cpu_node, gpu_node],
    )

    assert selected == gpu_node
