from app.application.services.assign_worker_service import (
    AssignWorkerService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.entities.job import Job
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.enums.job_status import JobStatus
from app.domain.enums.worker_status import WorkerStatus
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)


class InMemoryWorkerRepository(
    WorkerRepository,
):
    def __init__(self) -> None:
        self._workers: dict[str, Worker] = {}

    def save(
        self,
        worker: Worker,
    ) -> None:
        self._workers[worker.id] = worker

    def get_by_id(
        self,
        worker_id: str,
    ) -> Worker | None:
        return self._workers.get(worker_id)

    def list(
        self,
    ) -> list[Worker]:
        return list(
            self._workers.values()
        )

    def delete(
        self,
        worker_id: str,
    ) -> None:
        self._workers.pop(
            worker_id,
            None,
        )


def test_assign_worker_service_assigns_job_to_idle_worker() -> None:
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = Worker(
        id="worker-1",
        node=node,
    )

    worker.ready()

    repository = InMemoryWorkerRepository()

    repository.save(
        worker,
    )

    job = Job(
        id="job-1",
        resources=ResourceRequirements(
            cpu_cores=2,
            memory_mib=2048,
            vram_mib=0,
        ),
    )

    job.queue()
    job.assign_to(
        node.id,
    )

    service = AssignWorkerService(
        repository,
    )

    assigned_worker = service.execute(
        job,
    )

    assert assigned_worker is worker

    assert worker.running_job is job

    assert worker.status is WorkerStatus.BUSY

    assert job.status is JobStatus.RUNNING
def test_assign_worker_service_records_worker_assigned_event() -> None:
    """
    Assigning a job to a worker must record a WorkerAssigned
    event, the same way scheduling already records JobScheduled.
    """
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = Worker(
        id="worker-1",
        node=node,
    )
    worker.ready()

    repository = InMemoryWorkerRepository()
    repository.save(
        worker,
    )

    job = Job(
        id="job-1",
        resources=ResourceRequirements(
            cpu_cores=2,
            memory_mib=2048,
            vram_mib=0,
        ),
    )
    job.queue()
    job.assign_to(
        node.id,
    )

    events = InMemoryEventRepository()

    record_job_events_service = RecordJobEventsService(
        event_repository=events,
    )

    service = AssignWorkerService(
        repository,
        record_job_events_service=record_job_events_service,
    )

    service.execute(
        job,
    )

    recorded = events.list()

    assert len(recorded) == 1
    assert recorded[0].event_type == "WorkerAssigned"
    assert recorded[0].aggregate_id == str(job.id)
    assert recorded[0].aggregate_type == "Job"
