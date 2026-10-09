from app.domain.entities.job import Job
from app.domain.services.job_lifecycle import JobLifecycle
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from tests.support.jobs import make_job


def create_job() -> Job:
    return make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
    )


def test_job_lifecycle_service_happy_path() -> None:
    lifecycle = JobLifecycle()

    job = create_job()

    lifecycle.queue(
        job,
    )

    assert job.is_queued()

    lifecycle.schedule(
        job,
        NodeId.new(),
    )

    assert job.is_scheduled()

    lifecycle.start(
        job,
    )

    assert job.is_running()

    lifecycle.complete(
        job,
    )

    assert job.is_completed()
