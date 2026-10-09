from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)
from tests.support.jobs import make_job


def test_record_job_created_event() -> None:
    job = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=2,
            memory_mib=1024,
            vram_mib=0,
        ),
    )

    repository = InMemoryEventRepository()

    service = RecordJobEventsService(
        event_repository=repository,
    )

    service.record(
        aggregate_id=str(job.id),
        event_type="JobCreated",
    )

    events = repository.list()

    assert len(events) == 1

    event = events[0]

    assert event.aggregate_id == str(job.id)
    assert event.event_type == "JobCreated"


def test_record_multiple_events_for_same_job() -> None:
    job = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
    )

    repository = InMemoryEventRepository()

    service = RecordJobEventsService(
        event_repository=repository,
    )

    service.record(
        aggregate_id=str(job.id),
        event_type="JobCreated",
    )

    service.record(
        aggregate_id=str(job.id),
        event_type="JobScheduled",
    )

    service.record(
        aggregate_id=str(job.id),
        event_type="JobRunning",
    )

    events = repository.list_by_aggregate(
        str(job.id),
    )

    assert len(events) == 3

    assert events[0].event_type == "JobCreated"
    assert events[1].event_type == "JobScheduled"
    assert events[2].event_type == "JobRunning"
