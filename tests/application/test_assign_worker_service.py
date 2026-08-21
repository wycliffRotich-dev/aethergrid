import pytest

from app.application.services.acquire_lease_service import (
    AcquireLeaseService,
)
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
from app.domain.exceptions.no_available_node_error import (
    NoAvailableNodeError,
)
from app.domain.exceptions.worker_not_found_error import (
    WorkerNotFoundError,
)
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

    # Assignment means the worker now holds the job, not that
    # execution has begun. The job stays SCHEDULED until an
    # agent explicitly confirms it has started running (see
    # ADR 0019) -- reporting RUNNING any earlier would be the
    # system lying about its own state.
    assert job.status is JobStatus.SCHEDULED
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


class _LeaseRepositoryThatRejectsUnknownWorker:
    """
    Stand-in for PostgresLeaseRepository.save() raising
    WorkerNotFoundError when the worker's foreign key no
    longer exists -- e.g. its node was concurrently removed
    by RemoveOfflineNodeService (workers.node_id is ON DELETE
    CASCADE), deleting the worker between AssignWorkerService
    reading it as an idle candidate and AcquireLeaseService
    trying to persist a lease for it. See ADR 0027.
    """

    def get_by_job_id(
        self,
        job_id,
    ):
        return None

    def save(
        self,
        lease,
    ) -> None:
        raise WorkerNotFoundError(
            lease.worker_id,
        )


def test_assign_worker_service_raises_no_available_node_when_worker_vanishes() -> None:
    """
    If the worker selected as an assignment candidate is
    deleted before its lease can be persisted -- most likely
    because its node went offline and was removed, cascading
    the delete to this worker -- AssignWorkerService must not
    let the underlying WorkerNotFoundError propagate raw. It
    should be indistinguishable from "no idle worker was
    available", so SchedulerLoopService's existing recovery
    path (unschedule the job, release the node's capacity,
    retry on the next tick) handles it without any changes of
    its own. See ADR 0027.
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

    worker_repository = InMemoryWorkerRepository()
    worker_repository.save(
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

    acquire_lease_service = AcquireLeaseService(
        _LeaseRepositoryThatRejectsUnknownWorker(),
    )

    service = AssignWorkerService(
        worker_repository,
        acquire_lease_service=acquire_lease_service,
    )

    with pytest.raises(NoAvailableNodeError):
        service.execute(
            job,
        )

    # Note: InMemoryWorkerRepository stores the worker by
    # reference, so worker.accept(job)'s in-memory mutation is
    # visible here regardless of whether save() was called
    # again afterwards. That distinction only exists once a
    # repository actually serializes state (e.g. Postgres),
    # which is why this test does not assert on repository
    # state after the exception -- it asserts on the one thing
    # that matters at this layer: the exception itself.
