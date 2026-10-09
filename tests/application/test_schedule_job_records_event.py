from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.services.job_lifecycle import JobLifecycle
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node


def test_record_job_scheduled_event() -> None:
    resources = ResourceRequirements(
        cpu_cores=2,
        memory_mib=2048,
        vram_mib=0,
    )

    job = make_job(
        id=JobId.new(),
        resources=resources,
    )

    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    lifecycle = JobLifecycle()

    lifecycle.queue(
        job,
    )

    lifecycle.schedule(
        job,
        node.id,
    )

    repository = InMemoryEventRepository()

    service = RecordJobEventsService(
        event_repository=repository,
    )

    service.record(
        aggregate_id=str(job.id),
        aggregate_type="Job",
        event_type="JobScheduled",
    )

    events = repository.list_by_aggregate(
        str(job.id),
    )

    assert len(events) == 1
    assert events[0].event_type == "JobScheduled"
