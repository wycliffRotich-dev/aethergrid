from app.application.services.fail_job_service import (
    FailJobService,
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


def test_fail_job_service_marks_running_job_as_failed() -> None:
    """
    A running job can transition to FAILED and
    release the resources allocated on its node.
    """

    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=16384,
        ),
    )

    job = make_job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=4,
            memory_mib=4096,
            vram_mib=2048,
        ),
    )

    job.queue()
    job.assign_to(node.id)

    node.allocate(
        job.resources,
    )

    job.start()

    job_repository = InMemoryJobRepository(
        [
            job,
        ],
    )

    node_repository = InMemoryNodeRepository(
        [
            node,
        ],
    )

    service = FailJobService(
        job_repository,
        node_repository,
    )

    service.execute(
        job.id,
        job.tenant_id,
    )

    assert job.status == JobStatus.FAILED

    assert node.available == node.capacity
def test_fail_job_service_persists_released_node_resources(
    tmp_path,
) -> None:
    """
    Regression test: failing a job must persist the node's
    released resources, not just mutate the in-memory Node
    object. Same gap and same reasoning as
    CompleteJobService's equivalent test (ADR 0033, 0037):
    verified against SqliteNodeRepository, not
    InMemoryNodeRepository, since an in-memory repository
    shares the same object reference on read and cannot
    distinguish a missing save() from a real one.
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

    service = FailJobService(
        job_repository,
        exec_node_repository,
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


def test_fail_job_service_fails_a_job_in_a_non_default_tenant() -> None:
    tenant = TenantId.new()
    assert tenant != DEFAULT_TENANT_ID
    job, node = _running_job_and_node(tenant, tenant)

    service = FailJobService(
        InMemoryJobRepository([job]),
        InMemoryNodeRepository([node]),
    )

    result = service.execute(job.id, tenant)

    assert result is job
    assert job.status == JobStatus.FAILED
    assert node.available == node.capacity


def test_fail_job_service_does_not_touch_a_job_in_another_tenant() -> None:
    """
    A caller in another tenant reads the job as missing: the result is
    None, the job keeps running and the node keeps its allocation.
    """
    tenant = TenantId.new()
    job, node = _running_job_and_node(tenant, tenant)

    service = FailJobService(
        InMemoryJobRepository([job]),
        InMemoryNodeRepository([node]),
    )

    result = service.execute(job.id, TenantId.new())

    assert result is None
    assert job.status == JobStatus.RUNNING
    assert node.available.cpu_cores == 4


def test_fail_job_service_does_not_use_a_node_of_another_tenant() -> None:
    """
    The database forbids a job assigned to a node of another tenant
    (ADR 0069). If that state ever existed, the scoped node read must
    fail closed: None, the job still running, the node untouched.
    """
    job_tenant = TenantId.new()
    node_tenant = TenantId.new()
    job, node = _running_job_and_node(job_tenant, node_tenant)

    service = FailJobService(
        InMemoryJobRepository([job]),
        InMemoryNodeRepository([node]),
    )

    result = service.execute(job.id, job_tenant)

    assert result is None
    assert job.status == JobStatus.RUNNING
    assert node.available.cpu_cores == 4
