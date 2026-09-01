from __future__ import annotations

import os
import tempfile

import pytest

from app.domain.entities.job import Job
from app.domain.enums.job_status import JobStatus
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.sqlite_connection import (
    create_connection,
)
from app.infrastructure.repositories.sqlite_job_repository import (
    SqliteJobRepository,
)


@pytest.fixture()
def db_path():
    """
    Provide a real temp-file SQLite database path so tests
    prove persistence across separate connections, not just
    reads from a shared in-process connection object.
    """
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)

    yield path

    os.remove(path)


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


def test_save_and_get_by_id_round_trips_full_job(db_path) -> None:
    job = _make_job(
        constraints={"gpu": "true"},
    )
    job.queue()
    job.assign_to(NodeId.new())

    write_connection = create_connection(db_path)
    write_repository = SqliteJobRepository(write_connection)
    write_repository.save(job)
    write_connection.close()

    # Fresh connection and fresh repository instance -- proves
    # the round trip survives independent of any in-memory state.
    read_connection = create_connection(db_path)
    read_repository = SqliteJobRepository(read_connection)
    reloaded = read_repository.get_by_id(job.id)
    read_connection.close()

    assert reloaded is not None
    assert reloaded.id == job.id
    assert reloaded.resources.cpu_cores == 2
    assert reloaded.resources.memory_mib == 2048
    assert reloaded.priority == 0
    assert reloaded.constraints == {"gpu": "true"}
    assert reloaded.max_retries == 3
    assert reloaded.status == JobStatus.SCHEDULED
    assert reloaded.assigned_node_id == job.assigned_node_id


def test_round_trips_job_with_no_assigned_node(db_path) -> None:
    job = _make_job()

    connection = create_connection(db_path)
    repository = SqliteJobRepository(connection)
    repository.save(job)

    reloaded = repository.get_by_id(job.id)

    assert reloaded is not None
    assert reloaded.assigned_node_id is None


def test_get_by_id_returns_none_when_not_found(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteJobRepository(connection)

    result = repository.get_by_id(JobId.new())

    assert result is None


def test_list_returns_all_saved_jobs(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteJobRepository(connection)

    first = _make_job()
    second = _make_job()
    repository.save(first)
    repository.save(second)

    result = repository.list()

    assert {job.id for job in result} == {first.id, second.id}


def test_list_queued_returns_only_queued_jobs(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteJobRepository(connection)

    queued = _make_job()
    queued.queue()

    submitted = _make_job()

    repository.save(queued)
    repository.save(submitted)

    result = repository.list_queued()

    assert queued.id in {job.id for job in result}
    assert submitted.id not in {job.id for job in result}


def test_save_twice_updates_existing_job_instead_of_duplicating(
    db_path,
) -> None:
    connection = create_connection(db_path)
    repository = SqliteJobRepository(connection)

    job = _make_job()
    repository.save(job)

    job.queue()
    repository.save(job)

    result = repository.list()
    matching = [j for j in result if j.id == job.id]

    assert len(matching) == 1
    assert matching[0].status == JobStatus.QUEUED


def test_round_trips_command_and_exit_code(db_path) -> None:
    """
    A job with a real command and a recorded exit code must
    survive a save/load cycle across independent
    connections intact -- these two fields did not exist
    before real subprocess execution was added, and nothing
    previously exercised them at all.
    """
    job = _make_job()
    job.command = ["python3", "-c", "print('hi')"]

    write_connection = create_connection(db_path)
    write_repository = SqliteJobRepository(write_connection)
    write_repository.save(job)
    write_connection.close()

    read_connection = create_connection(db_path)
    read_repository = SqliteJobRepository(read_connection)
    reloaded = read_repository.get_by_id(job.id)
    read_connection.close()

    assert reloaded is not None
    assert reloaded.command == ["python3", "-c", "print('hi')"]
    assert reloaded.exit_code is None

    job.queue()
    job.assign_to(NodeId.new())
    job.exit_code = 0

    write_connection = create_connection(db_path)
    write_repository = SqliteJobRepository(write_connection)
    write_repository.save(job)
    write_connection.close()

    read_connection = create_connection(db_path)
    read_repository = SqliteJobRepository(read_connection)
    reloaded_after_update = read_repository.get_by_id(job.id)
    read_connection.close()

    assert reloaded_after_update is not None
    assert reloaded_after_update.exit_code == 0


def test_round_trips_job_with_no_command(db_path) -> None:
    """
    A job with no command (the current default for every
    job created through the public API) must round-trip as
    None, not as the string "null" or an empty list.
    """
    job = _make_job()
    assert job.command is None

    connection = create_connection(db_path)
    repository = SqliteJobRepository(connection)
    repository.save(job)

    reloaded = repository.get_by_id(job.id)

    assert reloaded is not None
    assert reloaded.command is None


def test_round_trips_started_at_and_completed_at(db_path) -> None:
    """
    started_at and completed_at must survive a save/load
    cycle across independent connections. Neither column
    previously existed in the SQLite schema at all, so both
    were silently dropped on every save.
    """
    job = _make_job()
    job.queue()
    job.assign_to(NodeId.new())
    job.start()

    write_connection = create_connection(db_path)
    write_repository = SqliteJobRepository(write_connection)
    write_repository.save(job)
    write_connection.close()

    read_connection = create_connection(db_path)
    read_repository = SqliteJobRepository(read_connection)
    reloaded = read_repository.get_by_id(job.id)
    read_connection.close()

    assert reloaded is not None
    assert reloaded.started_at is not None
    assert reloaded.started_at == job.started_at
    assert reloaded.completed_at is None

    job.complete(exit_code=0)

    write_connection = create_connection(db_path)
    write_repository = SqliteJobRepository(write_connection)
    write_repository.save(job)
    write_connection.close()

    read_connection = create_connection(db_path)
    read_repository = SqliteJobRepository(read_connection)
    reloaded_after_completion = read_repository.get_by_id(job.id)
    read_connection.close()

    assert reloaded_after_completion is not None
    assert reloaded_after_completion.completed_at is not None
    assert reloaded_after_completion.completed_at == job.completed_at
