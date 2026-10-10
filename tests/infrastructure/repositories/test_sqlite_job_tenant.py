from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.enums.job_status import JobStatus
from app.domain.exceptions.job_tenant_conflict_error import (
    JobTenantConflictError,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.sqlite_connection import (
    create_connection,
)
from app.infrastructure.repositories.sqlite_job_repository import (
    SqliteJobRepository,
)
from tests.support.jobs import make_job

# The jobs table exactly as it was before ADR 0064 added a tenant.
_PRE_TENANT_TABLE = """
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    cpu_cores INTEGER NOT NULL,
    memory_mib INTEGER NOT NULL,
    vram_mib INTEGER NOT NULL,
    priority INTEGER NOT NULL,
    constraints TEXT NOT NULL,
    max_retries INTEGER NOT NULL,
    retry_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    assigned_node_id TEXT,
    submitted_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    command TEXT,
    exit_code INTEGER,
    cancellation_requested_at TEXT
);
"""


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "jobs.db")


def test_a_saved_job_keeps_its_tenant(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteJobRepository(connection)
    tenant_id = TenantId.new()
    job = make_job(tenant_id=tenant_id)

    repository.save(job)

    fetched = repository.get_by_id(job.id, tenant_id)
    connection.close()
    assert fetched is not None
    assert fetched.tenant_id == tenant_id


def test_saving_a_job_id_held_by_another_tenant_conflicts(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteJobRepository(connection)
    job = make_job(priority=1)
    repository.save(job)
    intruder = make_job(
        id=job.id,
        tenant_id=TenantId.new(),
        priority=9,
    )

    with pytest.raises(JobTenantConflictError):
        repository.save(intruder)

    stored = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    connection.close()
    assert stored is not None
    assert stored.tenant_id == DEFAULT_TENANT_ID
    assert stored.priority == 1


def test_across_tenants_reads_see_jobs_in_every_tenant(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteJobRepository(connection)
    their_tenant_id = TenantId.new()
    mine = make_job()
    theirs = make_job(tenant_id=their_tenant_id)
    repository.save(mine)
    repository.save(theirs)

    listed = repository.list_across_tenants()
    fetched = repository.get_by_id_across_tenants(theirs.id)
    missing = repository.get_by_id_across_tenants(make_job().id)
    connection.close()

    assert {job.id for job in listed} == {mine.id, theirs.id}
    assert fetched is not None
    assert fetched.tenant_id == their_tenant_id
    assert missing is None


def test_get_by_id_in_another_tenant_returns_none(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteJobRepository(connection)
    job = make_job()
    repository.save(job)

    foreign = repository.get_by_id(job.id, TenantId.new())
    owner = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    connection.close()

    assert foreign is None
    assert owner is not None


def test_list_recent_returns_only_the_callers_tenant(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteJobRepository(connection)
    their_tenant_id = TenantId.new()
    mine = make_job()
    theirs = make_job(tenant_id=their_tenant_id)
    repository.save(mine)
    repository.save(theirs)

    in_default = repository.list_recent(10, DEFAULT_TENANT_ID)
    in_theirs = repository.list_recent(10, their_tenant_id)
    connection.close()

    assert [job.id for job in in_default] == [mine.id]
    assert [job.id for job in in_theirs] == [theirs.id]


def test_list_queued_returns_only_the_callers_tenant(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteJobRepository(connection)
    their_tenant_id = TenantId.new()
    mine = make_job()
    theirs = make_job(tenant_id=their_tenant_id)
    mine.queue()
    theirs.queue()
    repository.save(mine)
    repository.save(theirs)

    in_default = repository.list_queued(DEFAULT_TENANT_ID)
    in_theirs = repository.list_queued(their_tenant_id)
    connection.close()

    assert [job.id for job in in_default] == [mine.id]
    assert [job.id for job in in_theirs] == [theirs.id]


def _insert_pre_tenant_job(db_path: str, job_id: JobId) -> None:
    raw = sqlite3.connect(db_path)
    raw.execute(_PRE_TENANT_TABLE)
    raw.execute(
        "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(job_id),
            2,
            2048,
            0,
            0,
            "{}",
            3,
            0,
            JobStatus.QUEUED.value,
            None,
            datetime.now(UTC).isoformat(),
            None,
            None,
            None,
            None,
            None,
        ),
    )
    raw.commit()
    raw.close()


def test_upgrade_assigns_pre_tenant_rows_to_the_default_tenant(
    db_path,
) -> None:
    job_id = JobId.new()
    _insert_pre_tenant_job(db_path, job_id)

    connection = create_connection(db_path)
    repository = SqliteJobRepository(connection)

    fetched = repository.get_by_id(job_id, DEFAULT_TENANT_ID)
    connection.close()
    assert fetched is not None
    assert fetched.tenant_id == DEFAULT_TENANT_ID
    assert fetched.max_retries == 3


def test_opening_an_upgraded_file_again_changes_nothing(db_path) -> None:
    job_id = JobId.new()
    _insert_pre_tenant_job(db_path, job_id)

    connection = create_connection(db_path)
    SqliteJobRepository(connection)
    connection.close()

    connection = create_connection(db_path)
    repository = SqliteJobRepository(connection)
    fetched = repository.get_by_id(job_id, DEFAULT_TENANT_ID)
    connection.close()

    assert fetched is not None
    assert fetched.tenant_id == DEFAULT_TENANT_ID
