from app.application.services.fail_job_service import (
    FailJobService,
)
from app.domain.entities.job import Job
from app.domain.entities.node import Node
from app.domain.enums.job_status import JobStatus
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)


def test_fail_job_service_marks_running_job_as_failed() -> None:
    """
    A running job can transition to FAILED and
    release the resources allocated on its node.
    """

    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=16384,
        ),
    )

    job = Job(
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

    node = Node(
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

    job = Job(
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

    service.execute(job.id)
    exec_connection.close()

    read_connection = create_connection(db_path)
    read_node_repository = SqliteNodeRepository(read_connection)
    reloaded = read_node_repository.get_by_id(node.id)
    read_connection.close()

    assert reloaded is not None
    assert reloaded.available.cpu_cores == 8
    assert reloaded.available.memory_mib == 16384

