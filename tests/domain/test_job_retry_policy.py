from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from tests.support.jobs import make_job


def test_job_can_retry_until_max_retries() -> None:
    """
    A job may only retry up to its
    configured retry limit.
    """

    job = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
        max_retries=2,
    )

    assert job.can_retry()

    job.record_retry()

    assert job.can_retry()

    job.record_retry()

    assert not job.can_retry()
