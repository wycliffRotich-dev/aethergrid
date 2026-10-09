from __future__ import annotations

import pytest

from app.application.services.get_job_service import (
    GetJobService,
)
from app.domain.exceptions.job_not_found_error import (
    JobNotFoundError,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from tests.support.jobs import make_job


def test_get_job_service_returns_existing_job() -> None:
    repository = InMemoryJobRepository()

    job = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=8192,
            vram_mib=2048,
        ),
    )

    repository.save(job)

    service = GetJobService(
        job_repository=repository,
    )

    retrieved = service.execute(job.id)

    assert retrieved is job


def test_get_job_service_raises_when_job_does_not_exist() -> None:
    repository = InMemoryJobRepository()

    service = GetJobService(
        job_repository=repository,
    )

    missing_job_id = JobId.new()

    with pytest.raises(JobNotFoundError):
        service.execute(missing_job_id)
