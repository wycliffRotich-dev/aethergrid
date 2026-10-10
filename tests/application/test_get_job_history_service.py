from app.application.services.get_job_history_service import (
    GetJobHistoryService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from tests.support.jobs import make_job

_EVENT_TYPES = ("JobCreated", "JobQueued", "JobScheduled")


def _record_history(
    event_repository: InMemoryEventRepository,
    aggregate_id: str,
) -> None:
    recorder = RecordJobEventsService(
        event_repository=event_repository,
    )

    for event_type in _EVENT_TYPES:
        recorder.record(
            aggregate_id=aggregate_id,
            aggregate_type="Job",
            event_type=event_type,
        )


def test_returns_job_history() -> None:
    job = make_job()
    event_repository = InMemoryEventRepository()
    _record_history(event_repository, str(job.id))

    service = GetJobHistoryService(
        job_repository=InMemoryJobRepository([job]),
        event_repository=event_repository,
    )

    events = service.execute(
        aggregate_id=str(job.id),
        tenant_id=DEFAULT_TENANT_ID,
    )

    assert [event.event_type for event in events] == list(_EVENT_TYPES)


def test_a_job_in_another_tenant_has_no_history() -> None:
    """
    Events carry no tenant, so the job is checked first. The
    owner's call is the control: it proves the events exist.
    """
    job = make_job()
    event_repository = InMemoryEventRepository()
    _record_history(event_repository, str(job.id))

    service = GetJobHistoryService(
        job_repository=InMemoryJobRepository([job]),
        event_repository=event_repository,
    )

    foreign = service.execute(
        aggregate_id=str(job.id),
        tenant_id=TenantId.new(),
    )
    owner = service.execute(
        aggregate_id=str(job.id),
        tenant_id=DEFAULT_TENANT_ID,
    )

    assert foreign == []
    assert len(owner) == len(_EVENT_TYPES)


def test_a_missing_job_has_no_history() -> None:
    never_saved = make_job()
    event_repository = InMemoryEventRepository()
    _record_history(event_repository, str(never_saved.id))

    service = GetJobHistoryService(
        job_repository=InMemoryJobRepository(),
        event_repository=event_repository,
    )

    events = service.execute(
        aggregate_id=str(never_saved.id),
        tenant_id=DEFAULT_TENANT_ID,
    )

    assert events == []


def test_an_id_that_is_not_a_uuid_has_no_history() -> None:
    event_repository = InMemoryEventRepository()
    _record_history(event_repository, "job-123")

    service = GetJobHistoryService(
        job_repository=InMemoryJobRepository(),
        event_repository=event_repository,
    )

    events = service.execute(
        aggregate_id="job-123",
        tenant_id=DEFAULT_TENANT_ID,
    )

    assert events == []
