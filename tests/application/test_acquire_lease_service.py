from app.application.services.acquire_lease_service import (
    AcquireLeaseService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.job import Job
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)
from app.infrastructure.repositories.in_memory_lease_repository import (
    InMemoryLeaseRepository,
)


def test_worker_can_acquire_job_lease() -> None:
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=4,
            memory_mib=4096,
            vram_mib=0,
        ),
    )

    worker = Worker(
        id=WorkerId.new(),
        node=node,
    )

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
    )

    repository = InMemoryLeaseRepository()

    service = AcquireLeaseService(
        repository,
    )

    lease = service.execute(
        worker,
        job,
    )

    assert lease.worker_id == worker.id
    assert lease.job_id == job.id
    assert repository.get_by_job_id(job.id) is not None
def test_acquire_lease_service_records_lease_acquired_event() -> None:
    """
    Acquiring a lease must record a LeaseAcquired event, the
    same way assignment already records WorkerAssigned.
    """
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=4,
            memory_mib=4096,
            vram_mib=0,
        ),
    )

    worker = Worker(
        id=WorkerId.new(),
        node=node,
    )

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
    )

    repository = InMemoryLeaseRepository()
    events = InMemoryEventRepository()

    record_job_events_service = RecordJobEventsService(
        event_repository=events,
    )

    service = AcquireLeaseService(
        repository,
        record_job_events_service=record_job_events_service,
    )

    service.execute(
        worker,
        job,
    )

    recorded = events.list()

    assert len(recorded) == 1
    assert recorded[0].event_type == "LeaseAcquired"
    assert recorded[0].aggregate_id == str(job.id)
    assert recorded[0].aggregate_type == "Job"
