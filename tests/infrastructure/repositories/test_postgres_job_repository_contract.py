from __future__ import annotations

import pytest
from psycopg_pool import ConnectionPool

from app.domain.entities.job import Job
from app.domain.entities.node import Node
from app.domain.enums.job_status import JobStatus
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.postgres_job_repository import (
    PostgresJobRepository,
)
from app.infrastructure.repositories.postgres_node_repository import (
    PostgresNodeRepository,
)


@pytest.fixture(scope="session")
def pool(test_database_url):
    test_pool = ConnectionPool(
        test_database_url,
        min_size=1,
        max_size=5,
        open=True,
        kwargs={"autocommit": True},
    )
    yield test_pool
    test_pool.close()


@pytest.fixture()
def node_repository(pool):
    return PostgresNodeRepository(pool)


@pytest.fixture()
def repository(pool):
    with pool.connection() as conn:
        conn.execute("TRUNCATE jobs, nodes CASCADE")
    return PostgresJobRepository(pool)


def _make_job(
    cpu_cores: int = 2,
    memory_mib: int = 2048,
    priority: int = 0,
    constraints: dict[str, str] | None = None,
    max_retries: int = 3,
) -> Job:
    return Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=cpu_cores,
            memory_mib=memory_mib,
        ),
        priority=priority,
        constraints=constraints or {},
        max_retries=max_retries,
    )


def _make_node() -> Node:
    return Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )


def test_save_and_get_by_id_round_trips_full_job(
    repository,
    node_repository,
) -> None:
    node = _make_node()
    node_repository.save(node)

    job = _make_job(constraints={"gpu": "true"})
    job.queue()
    job.assign_to(node.id)

    repository.save(job)

    reloaded = repository.get_by_id(job.id)

    assert reloaded is not None
    assert reloaded.id == job.id
    assert reloaded.resources.cpu_cores == 2
    assert reloaded.resources.memory_mib == 2048
    assert reloaded.priority == 0
    assert reloaded.constraints == {"gpu": "true"}
    assert reloaded.max_retries == 3
    assert reloaded.status == JobStatus.SCHEDULED
    assert reloaded.assigned_node_id == job.assigned_node_id


def test_round_trips_job_with_no_assigned_node(repository) -> None:
    job = _make_job()

    repository.save(job)
    reloaded = repository.get_by_id(job.id)

    assert reloaded is not None
    assert reloaded.assigned_node_id is None


def test_get_by_id_returns_none_when_not_found(repository) -> None:
    result = repository.get_by_id(JobId.new())
    assert result is None


def test_list_returns_all_saved_jobs(repository) -> None:
    first = _make_job()
    second = _make_job()
    repository.save(first)
    repository.save(second)

    result = repository.list()

    assert {job.id for job in result} == {first.id, second.id}


def test_list_queued_returns_only_queued_jobs(repository) -> None:
    queued = _make_job()
    queued.queue()

    submitted = _make_job()

    repository.save(queued)
    repository.save(submitted)

    result = repository.list_queued()

    assert queued.id in {job.id for job in result}
    assert submitted.id not in {job.id for job in result}


def test_save_twice_updates_existing_job_instead_of_duplicating(
    repository,
) -> None:
    job = _make_job()
    repository.save(job)

    job.queue()
    repository.save(job)

    result = repository.list()
    matching = [j for j in result if j.id == job.id]

    assert len(matching) == 1
    assert matching[0].status == JobStatus.QUEUED


def test_round_trips_command_and_exit_code(repository) -> None:
    """
    A job with a real command and a recorded exit code must
    survive a save/load cycle -- these two fields did not
    exist before real subprocess execution was added, and
    nothing previously exercised them against PostgreSQL.
    """
    job = _make_job()
    job.command = ["python3", "-c", "print('hi')"]

    repository.save(job)
    reloaded = repository.get_by_id(job.id)

    assert reloaded is not None
    assert reloaded.command == ["python3", "-c", "print('hi')"]
    assert reloaded.exit_code is None

    job.exit_code = 0
    repository.save(job)
    reloaded_after_update = repository.get_by_id(job.id)

    assert reloaded_after_update is not None
    assert reloaded_after_update.exit_code == 0


def test_round_trips_job_with_no_command(repository) -> None:
    """
    A job with no command (the current default for every
    job created through the public API) must round-trip as
    None, not as a JSON "null" string or an empty list.
    """
    job = _make_job()
    assert job.command is None

    repository.save(job)
    reloaded = repository.get_by_id(job.id)

    assert reloaded is not None
    assert reloaded.command is None
