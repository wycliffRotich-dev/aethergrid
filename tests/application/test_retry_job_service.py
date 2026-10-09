from app.application.services.retry_job_service import (
    RetryJobService,
)
from app.domain.enums.job_status import JobStatus
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node


def test_retry_service_requeues_failed_job() -> None:
    """
    Failed jobs with retries remaining
    should be requeued.
    """

    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=2,
            memory_mib=2048,
            vram_mib=0,
        ),
    )

    job = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
        max_retries=2,
    )

    job.queue()
    job.assign_to(node.id)
    job.start()
    job.fail()

    repository = InMemoryJobRepository(
        [
            job,
        ],
    )

    service = RetryJobService(
        repository,
    )

    retried = service.execute(
        job.id,
    )

    assert retried is not None
    assert retried.status == JobStatus.QUEUED
    assert retried.retry_count == 1
