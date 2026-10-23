from __future__ import annotations

from app.application.services.complete_job_service import (
    CompleteJobService,
)
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.enums.job_status import JobStatus
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node


def test_complete_job_service_completes_job() -> None:
    # 1. Instantiate the domain entity safely using its native dataclass fields
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=4096,
        ),
    )

    # 2. Seed the repository through the constructor as your code specifies
    node_repository = InMemoryNodeRepository(nodes=[node])
    job_repository = InMemoryJobRepository()

    job = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=8192,
            vram_mib=2048,
        ),
    )

    # 3. Follow your exact strict FSM state transitions to reach a valid running state
    job.queue()
    job.assign_to(node.id)
    node.allocate(job.resources)
    job.start()

    # 4. Persist the valid job aggregate
    job_repository.save(job)

    service = CompleteJobService(
        job_repository=job_repository,
        node_repository=node_repository,
    )

    completed = service.execute(job.id, job.tenant_id)

    assert completed is job
    assert completed.status == JobStatus.COMPLETED


def test_complete_job_service_returns_none_when_job_does_not_exist() -> None:
    job_repository = InMemoryJobRepository()
    node_repository = InMemoryNodeRepository()

    service = CompleteJobService(
        job_repository=job_repository,
        node_repository=node_repository,
    )

    result = service.execute(JobId.new(), DEFAULT_TENANT_ID)

    assert result is None


def test_complete_job_service_returns_none_when_job_has_no_assigned_node() -> None:
    job_repository = InMemoryJobRepository()
    node_repository = InMemoryNodeRepository()

    job = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=8192,
            vram_mib=2048,
        ),
    )
    job_repository.save(job)

    service = CompleteJobService(
        job_repository=job_repository,
        node_repository=node_repository,
    )

    result = service.execute(job.id, job.tenant_id)

    assert result is None


def test_complete_job_service_returns_none_when_node_does_not_exist() -> None:
    job_repository = InMemoryJobRepository()
    node_repository = InMemoryNodeRepository()

    job = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=8192,
            vram_mib=2048,
        ),
    )

    # Transition to an assigned state using an unmapped NodeId boundary
    job.queue()
    fake_node_id = NodeId.new()
    job.assign_to(fake_node_id)

    job_repository.save(job)

    service = CompleteJobService(
        job_repository=job_repository,
        node_repository=node_repository,
    )

    result = service.execute(job.id, job.tenant_id)

    assert result is None
def test_complete_job_service_persists_released_node_resources(
    tmp_path,
) -> None:
    """
    Regression test: completing a job must persist the node's
    released resources, not just mutate the in-memory Node
    object. Before this was fixed, CompleteJobService called
    node.release() but never called node_repository.save(),
    so the release was invisible the moment the object left
    memory, exactly the shape of gap this codebase has already
    caught with SQLite/Postgres-backed tests rather than
    InMemoryNodeRepository, which shares object references on
    read and would have masked this regardless (ADR 0033,
    0037).
    """
    import os

    from app.infrastructure.repositories.sqlite_connection import (
        create_connection,
    )
    from app.infrastructure.repositories.sqlite_node_repository import (
        SqliteNodeRepository,
    )

    db_path = os.path.join(tmp_path, "test.db")

    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    job_resources = ResourceRequirements(
        cpu_cores=1,
        memory_mib=512,
        vram_mib=0,
    )

    job = make_job(
        id=JobId.new(),
        resources=job_resources,
    )

    job.queue()
    job.assign_to(node.id)
    node.allocate(job_resources)
    job.start()

    write_connection = create_connection(db_path)
    write_node_repository = SqliteNodeRepository(write_connection)
    write_node_repository.save(node)
    write_connection.close()

    job_repository = InMemoryJobRepository([job])

    exec_connection = create_connection(db_path)
    exec_node_repository = SqliteNodeRepository(exec_connection)

    service = CompleteJobService(
        job_repository=job_repository,
        node_repository=exec_node_repository,
    )

    service.execute(job.id, job.tenant_id)
    exec_connection.close()

    read_connection = create_connection(db_path)
    read_node_repository = SqliteNodeRepository(read_connection)
    reloaded = read_node_repository.get_by_id(node.id, DEFAULT_TENANT_ID)
    read_connection.close()

    assert reloaded is not None
    assert reloaded.available.cpu_cores == 8
    assert reloaded.available.memory_mib == 16384


def _running_job_and_node(job_tenant: TenantId, node_tenant: TenantId):
    node = make_node(
        id=NodeId.new(),
        tenant_id=node_tenant,
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=4096,
        ),
    )
    job = make_job(
        id=JobId.new(),
        tenant_id=job_tenant,
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=8192,
            vram_mib=2048,
        ),
    )
    job.queue()
    job.assign_to(node.id)
    node.allocate(job.resources)
    job.start()
    return job, node


def test_complete_job_service_completes_a_job_in_a_non_default_tenant() -> None:
    tenant = TenantId.new()
    assert tenant != DEFAULT_TENANT_ID
    job, node = _running_job_and_node(tenant, tenant)

    service = CompleteJobService(
        job_repository=InMemoryJobRepository([job]),
        node_repository=InMemoryNodeRepository(nodes=[node]),
    )

    result = service.execute(job.id, tenant)

    assert result is job
    assert job.status == JobStatus.COMPLETED
    assert node.available.cpu_cores == 8


def test_complete_job_service_does_not_touch_a_job_in_another_tenant() -> None:
    """
    A caller in another tenant reads the job as missing: the result is
    None, the job keeps running and the node keeps its allocation.
    """
    tenant = TenantId.new()
    job, node = _running_job_and_node(tenant, tenant)

    service = CompleteJobService(
        job_repository=InMemoryJobRepository([job]),
        node_repository=InMemoryNodeRepository(nodes=[node]),
    )

    result = service.execute(job.id, TenantId.new())

    assert result is None
    assert job.status == JobStatus.RUNNING
    assert node.available.cpu_cores == 4


def test_complete_job_service_does_not_use_a_node_of_another_tenant() -> None:
    """
    The database forbids a job assigned to a node of another tenant
    (ADR 0069). If that state ever existed, the scoped node read must
    fail closed: None, the job still running, the node untouched.
    """
    job_tenant = TenantId.new()
    node_tenant = TenantId.new()
    job, node = _running_job_and_node(job_tenant, node_tenant)

    service = CompleteJobService(
        job_repository=InMemoryJobRepository([job]),
        node_repository=InMemoryNodeRepository(nodes=[node]),
    )

    result = service.execute(job.id, job_tenant)

    assert result is None
    assert job.status == JobStatus.RUNNING
    assert node.available.cpu_cores == 4
