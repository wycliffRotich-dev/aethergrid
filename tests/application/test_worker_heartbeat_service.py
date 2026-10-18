import pytest

from app.application.services.worker_heartbeat_service import (
    WorkerHeartbeatService,
)
from app.domain.entities.tenant import Tenant
from app.domain.enums.worker_status import WorkerStatus
from app.domain.exceptions.worker_not_found_error import (
    WorkerNotFoundError,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node
from tests.support.workers import make_worker


def test_execute_refreshes_worker_heartbeat() -> None:
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = make_worker(
        id=WorkerId.new(),
        node=node,
    )

    repository = InMemoryWorkerRepository(
        [
            worker,
        ],
    )

    original = worker.last_seen_at

    service = WorkerHeartbeatService(
        repository,
    )

    service.execute(
        worker.id,
        node.tenant_id,
    )

    stored_worker = repository.get_by_id(
        worker.id,
    )

    assert stored_worker is not None
    assert stored_worker.last_seen_at > original


def test_execute_recovers_offline_worker_with_no_running_job() -> None:
    """
    ADR 0041, exercised through the real service/repository path:
    heartbeating an OFFLINE, jobless worker must persist it back to
    IDLE, not just refresh its timestamp.
    """
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = make_worker(
        id=WorkerId.new(),
        node=node,
    )
    worker.offline()

    repository = InMemoryWorkerRepository(
        [
            worker,
        ],
    )

    service = WorkerHeartbeatService(
        repository,
    )

    service.execute(
        worker.id,
        node.tenant_id,
    )

    stored_worker = repository.get_by_id(
        worker.id,
    )

    assert stored_worker is not None
    assert stored_worker.status is WorkerStatus.IDLE


def test_execute_does_not_recover_offline_worker_with_running_job() -> None:
    """
    ADR 0041's guard, exercised through the real service path: an
    OFFLINE worker holding a job must stay OFFLINE after a heartbeat,
    left for reconciliation to resolve instead.
    """
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = make_worker(
        id=WorkerId.new(),
        node=node,
    )

    job = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=1024,
            vram_mib=0,
        ),
    )
    job.queue()
    job.assign_to(node.id)

    worker.ready()
    worker.accept(job)
    worker.offline()

    repository = InMemoryWorkerRepository(
        [
            worker,
        ],
    )

    service = WorkerHeartbeatService(
        repository,
    )

    service.execute(
        worker.id,
        node.tenant_id,
    )

    stored_worker = repository.get_by_id(
        worker.id,
    )

    assert stored_worker is not None
    assert stored_worker.status is WorkerStatus.OFFLINE


def test_a_worker_in_another_tenant_is_not_heartbeated() -> None:
    worker = make_worker(
        id=WorkerId.new(),
        node=make_node(id=NodeId.new()),
    )
    original = worker.last_seen_at
    repository = InMemoryWorkerRepository(
        [
            worker,
        ],
    )
    service = WorkerHeartbeatService(
        repository,
    )

    with pytest.raises(WorkerNotFoundError):
        service.execute(
            worker.id,
            Tenant.create("other").id,
        )

    stored_worker = repository.get_by_id(
        worker.id,
    )

    assert stored_worker is not None
    assert stored_worker.last_seen_at == original


def test_a_missing_worker_is_not_found() -> None:
    service = WorkerHeartbeatService(
        InMemoryWorkerRepository(
            [],
        ),
    )

    with pytest.raises(WorkerNotFoundError):
        service.execute(
            WorkerId.new(),
            Tenant.create("any").id,
        )
