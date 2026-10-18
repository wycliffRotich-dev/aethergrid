from app.application.services.get_job_history_service import (
    GetJobHistoryService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.job import Job
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)
from tests.support.jobs import make_job

_EVENT_TYPES = ("JobCreated", "JobQueued", "JobScheduled")


def _record_history(
    event_repository: InMemoryEventRepository,
    job: Job,
) -> None:
    recorder = RecordJobEventsService(
        event_repository=event_repository,
    )

    for event_type in _EVENT_TYPES:
        recorder.record_for_job(
            job,
            event_type=event_type,
        )


def test_returns_job_history() -> None:
    job = make_job()
    event_repository = InMemoryEventRepository()
    _record_history(event_repository, job)

    service = GetJobHistoryService(
        event_repository=event_repository,
    )

    events = service.execute(
        aggregate_id=str(job.id),
        tenant_id=DEFAULT_TENANT_ID,
    )

    assert [event.event_type for event in events] == list(_EVENT_TYPES)


def test_a_job_in_another_tenant_has_no_history() -> None:
    """
    Events carry the tenant of their job and history reads by it, so
    a job in another tenant has no history. The owner's call is the
    control: it proves the events exist.
    """
    job = make_job()
    event_repository = InMemoryEventRepository()
    _record_history(event_repository, job)

    service = GetJobHistoryService(
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


def test_a_job_with_no_events_has_no_history() -> None:
    """
    The read is made inside the caller's tenant (ADR 0074). A job
    id with no events there, whether the job is missing or has
    never recorded anything, gets the same empty answer. The
    other job's history is the control: it proves events exist.
    """
    recorded = make_job()
    silent = make_job()
    event_repository = InMemoryEventRepository()
    _record_history(event_repository, recorded)

    service = GetJobHistoryService(
        event_repository=event_repository,
    )

    events = service.execute(
        aggregate_id=str(silent.id),
        tenant_id=DEFAULT_TENANT_ID,
    )
    control = service.execute(
        aggregate_id=str(recorded.id),
        tenant_id=DEFAULT_TENANT_ID,
    )

    assert events == []
    assert len(control) == len(_EVENT_TYPES)


def test_an_id_that_is_not_a_uuid_has_no_history() -> None:
    job = make_job()
    event_repository = InMemoryEventRepository()
    _record_history(event_repository, job)

    service = GetJobHistoryService(
        event_repository=event_repository,
    )

    events = service.execute(
        aggregate_id="job-123",
        tenant_id=DEFAULT_TENANT_ID,
    )

    assert events == []
