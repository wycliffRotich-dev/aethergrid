from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from tests.support.jobs import make_job


def test_job_can_store_constraints() -> None:
    """
    A job should expose scheduling constraints.
    """

    job = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=2,
            memory_mib=2048,
            vram_mib=1024,
        ),
    )

    job.constraints["gpu"] = "true"
    job.constraints["region"] = "eu-west"

    assert job.constraints["gpu"] == "true"
    assert job.constraints["region"] == "eu-west"
