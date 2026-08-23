from __future__ import annotations

from app.application.services.create_job_service import (
    CreateJobService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.job import Job
from app.domain.enums.job_status import JobStatus
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)


def test_create_job_service_creates_and_persists_job() -> None:
    """
    Creating a job should persist it in the QUEUED state.

    Scheduling is intentionally not performed here. Newly
    created jobs are left queued until the background
    SchedulerLoopService processes them.
    """
    job_repository = InMemoryJobRepository()
    event_repository = InMemoryEventRepository()

    record_job_events_service = RecordJobEventsService(
        event_repository=event_repository,
    )

    service = CreateJobService(
        job_repository=job_repository,
        record_job_events_service=record_job_events_service,
    )

    resources = ResourceRequirements(
        cpu_cores=4,
        memory_mib=8192,
        vram_mib=2048,
    )

    job = service.execute(
        resources,
    )

    assert isinstance(
        job,
        Job,
    )

    stored = job_repository.get_by_id(
        job.id,
    )

    assert stored is not None
    assert stored.id == job.id
    assert stored.resources == resources
    assert stored.status == JobStatus.QUEUED


def test_create_job_service_records_job_created_event() -> None:
    """
    Creating a job must always record a JobCreated event.

    Event recording is independent from scheduling.
    """
    job_repository = InMemoryJobRepository()
    event_repository = InMemoryEventRepository()

    record_job_events_service = RecordJobEventsService(
        event_repository=event_repository,
    )

    service = CreateJobService(
        job_repository=job_repository,
        record_job_events_service=record_job_events_service,
    )

    resources = ResourceRequirements(
        cpu_cores=4,
        memory_mib=8192,
        vram_mib=2048,
    )

    job = service.execute(
        resources,
    )

    events = event_repository.list_by_aggregate(
        str(job.id),
    )

    assert len(events) == 1
    assert events[0].event_type == "JobCreated"


def test_create_job_service_does_not_schedule_job() -> None:
    """
    Creating a job must not perform scheduling.

    Scheduling is owned exclusively by SchedulerLoopService,
    ensuring every job follows the same scheduling path.
    """
    job_repository = InMemoryJobRepository()
    event_repository = InMemoryEventRepository()

    record_job_events_service = RecordJobEventsService(
        event_repository=event_repository,
    )

    service = CreateJobService(
        job_repository=job_repository,
        record_job_events_service=record_job_events_service,
    )

    job = service.execute(
        ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
    )

    stored = job_repository.get_by_id(
        job.id,
    )

    assert stored is not None
    assert stored.status == JobStatus.QUEUED
    assert stored.assigned_node_id is None

    events = event_repository.list_by_aggregate(
        str(job.id),
    )

    event_types = [
        event.event_type
        for event in events
    ]

    assert event_types == [
        "JobCreated",
    ]


def test_create_job_service_persists_command() -> None:
    """
    A command passed to execute() must be stored on the
    created job, so it can later be read by an assigned
    worker (ADR 0020) and actually run (ADR 0012, ADR 0028).
    """
    job_repository = InMemoryJobRepository()
    event_repository = InMemoryEventRepository()

    record_job_events_service = RecordJobEventsService(
        event_repository=event_repository,
    )

    service = CreateJobService(
        job_repository=job_repository,
        record_job_events_service=record_job_events_service,
    )

    job = service.execute(
        ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
        command=["python", "train.py"],
    )

    stored = job_repository.get_by_id(
        job.id,
    )

    assert stored is not None
    assert stored.command == ["python", "train.py"]


def test_create_job_service_defaults_command_to_none() -> None:
    """
    Every job created before ADR 0028 relied on command
    defaulting to None. That default must not change for
    callers who don't pass command at all.
    """
    job_repository = InMemoryJobRepository()
    event_repository = InMemoryEventRepository()

    record_job_events_service = RecordJobEventsService(
        event_repository=event_repository,
    )

    service = CreateJobService(
        job_repository=job_repository,
        record_job_events_service=record_job_events_service,
    )

    job = service.execute(
        ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
    )

    assert job.command is None
