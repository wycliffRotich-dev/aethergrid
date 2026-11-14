"""JobRepository.save_if_leaseless on the in-memory and SQLite backends
(ADR 0096).

Both keep leases in this process, so the fence is atomic only against
writers in this process. Postgres has its own tests, with real
transactions.
"""

from __future__ import annotations

import copy
import sqlite3

import pytest

from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.enums.job_status import JobStatus
from app.domain.repositories.job_repository import JobRepository
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from app.infrastructure.repositories.in_memory_lease_repository import (
    InMemoryLeaseRepository,
)
from app.infrastructure.repositories.sqlite_connection import (
    create_connection,
)
from app.infrastructure.repositories.sqlite_job_repository import (
    SqliteJobRepository,
)
from tests.support.jobs import make_job


@pytest.fixture(params=["memory", "sqlite"])
def backend(
    request: pytest.FixtureRequest, tmp_path
) -> tuple[JobRepository, InMemoryLeaseRepository]:
    leases = InMemoryLeaseRepository()

    if request.param == "memory":
        return InMemoryJobRepository(lease_repository=leases), leases

    connection: sqlite3.Connection = create_connection(
        str(tmp_path / "jobs.db")
    )
    return SqliteJobRepository(connection, lease_repository=leases), leases


def _running_job(repository: JobRepository) -> Job:
    job = make_job(max_retries=3)
    job.queue()
    job.assign_to(NodeId.new())
    job.start()
    repository.save(job)
    return job


def _copy_of(repository: JobRepository, job: Job) -> Job:
    """
    A copy of the stored job. The in-memory repository returns the
    object it stores, so a caller that changes it before the write
    changes what the write compares against. The service copies for
    the same reason.
    """
    found = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert found is not None
    return copy.deepcopy(found)


def _reclaimed(job: Job) -> Job:
    job.reclaim()
    return job


def test_it_saves_a_job_that_kept_its_status_and_has_no_lease(
    backend: tuple[JobRepository, InMemoryLeaseRepository],
) -> None:
    repository, _ = backend
    job = _running_job(repository)
    candidate = _copy_of(repository, job)

    assert repository.save_if_leaseless(
        _reclaimed(candidate), frozenset({JobStatus.RUNNING})
    )

    stored = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert stored is not None
    assert stored.status is JobStatus.QUEUED


def test_it_refuses_a_job_whose_status_changed(
    backend: tuple[JobRepository, InMemoryLeaseRepository],
) -> None:
    repository, _ = backend
    job = _running_job(repository)
    candidate = _copy_of(repository, job)

    finished = _copy_of(repository, job)
    finished.complete(exit_code=0)
    repository.save(finished)

    assert not repository.save_if_leaseless(
        _reclaimed(candidate), frozenset({JobStatus.RUNNING})
    )

    stored = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert stored is not None
    assert stored.status is JobStatus.COMPLETED


def test_it_refuses_a_job_that_has_a_lease(
    backend: tuple[JobRepository, InMemoryLeaseRepository],
) -> None:
    repository, leases = backend
    job = _running_job(repository)
    leases.save(
        Lease.create(
            worker_id=WorkerId.new(),
            job_id=job.id,
            tenant_id=job.tenant_id,
        )
    )
    candidate = _copy_of(repository, job)

    assert not repository.save_if_leaseless(
        _reclaimed(candidate), frozenset({JobStatus.RUNNING})
    )

    stored = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert stored is not None
    assert stored.status is JobStatus.RUNNING


def test_it_refuses_a_job_that_does_not_exist(
    backend: tuple[JobRepository, InMemoryLeaseRepository],
) -> None:
    repository, _ = backend
    job = make_job()
    job.queue()
    job.assign_to(NodeId.new())

    assert not repository.save_if_leaseless(job, frozenset({JobStatus.SCHEDULED}))


def test_it_does_not_reach_a_job_in_another_tenant(
    backend: tuple[JobRepository, InMemoryLeaseRepository],
) -> None:
    repository, _ = backend
    job = _running_job(repository)

    as_other_tenant = make_job(id=job.id, tenant_id=TenantId.new())
    as_other_tenant.queue()

    assert not repository.save_if_leaseless(
        as_other_tenant, frozenset({JobStatus.RUNNING})
    )

    stored = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
    assert stored is not None
    assert stored.status is JobStatus.RUNNING


def test_it_needs_the_lease_repository_it_checks_against() -> None:
    job = make_job()
    job.queue()
    job.assign_to(NodeId.new())

    with pytest.raises(RuntimeError, match="lease repository"):
        InMemoryJobRepository().save_if_leaseless(job, frozenset({JobStatus.SCHEDULED}))
