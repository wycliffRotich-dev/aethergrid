from app.application.services.list_queued_jobs_service import (
    ListQueuedJobsService,
)
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from tests.support.jobs import make_job


def test_list_queued_jobs_returns_only_queued_jobs() -> None:
    """
    Only queued jobs should be returned.
    """

    queued = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=2,
            memory_mib=2048,
            vram_mib=1024,
        ),
    )
    queued.queue()

    submitted = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=2,
            memory_mib=2048,
            vram_mib=1024,
        ),
    )

    repository = InMemoryJobRepository(
        [
            queued,
            submitted,
        ],
    )

    service = ListQueuedJobsService(
        repository,
    )

    jobs = service.execute(DEFAULT_TENANT_ID)

    assert queued in jobs
    assert submitted not in jobs
