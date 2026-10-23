from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from psycopg.rows import tuple_row
from psycopg_pool import ConnectionPool

from app.domain.entities.event import Event
from app.domain.entities.lease import utc_now
from app.domain.entities.tenant import DEFAULT_TENANT_ID, Tenant
from app.domain.value_objects.event_id import EventId
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.postgres_api_key_repository import (
    PostgresApiKeyRepository,
)
from app.infrastructure.repositories.postgres_event_repository import (
    PostgresEventRepository,
)
from app.infrastructure.repositories.postgres_job_repository import (
    PostgresJobRepository,
)
from app.infrastructure.repositories.postgres_lease_repository import (
    PostgresLeaseRepository,
)
from app.infrastructure.repositories.postgres_node_repository import (
    PostgresNodeRepository,
)
from app.infrastructure.repositories.postgres_tenant_repository import (
    PostgresTenantRepository,
)
from app.infrastructure.repositories.postgres_worker_repository import (
    PostgresWorkerRepository,
)
from tests.support.api_keys import make_api_key
from tests.support.jobs import make_job
from tests.support.nodes import make_node
from tests.support.workers import make_worker


@pytest.fixture
def single_connection_pool(test_database_url: str) -> Iterator[ConnectionPool]:
    """A pool of one, so the next borrower gets the connection the last used."""
    pool = ConnectionPool(
        test_database_url,
        min_size=1,
        max_size=1,
        open=True,
        kwargs={"autocommit": True},
    )
    try:
        pool.wait(timeout=10.0)
        yield pool
    finally:
        with pool.connection() as conn:
            conn.execute("DELETE FROM tenants WHERE name = 'row-factory-probe'")
        pool.close()


def _row_factory_after(pool: ConnectionPool) -> object:
    with pool.connection() as conn:
        return conn.row_factory


def test_the_tenant_repository_leaves_the_default_row_factory(
    single_connection_pool: ConnectionPool,
) -> None:
    """
    A repository must not change the row factory of the connection it
    borrows, because the pool hands that connection to the next caller.
    """
    repository = PostgresTenantRepository(single_connection_pool)
    tenant = Tenant.create("row-factory-probe")

    repository.save(tenant)
    repository.save(tenant)
    repository.get_by_id(tenant.id)
    repository.get_by_name(tenant.name)

    assert _row_factory_after(single_connection_pool) is tuple_row


def test_the_api_key_repository_leaves_the_default_row_factory(
    single_connection_pool: ConnectionPool,
) -> None:
    repository = PostgresApiKeyRepository(single_connection_pool)
    key, _raw = make_api_key("row-factory-probe")
    try:
        repository.save(key)
        repository.mark_used(key.id, DEFAULT_TENANT_ID)

        assert repository.get_by_id(key.id, DEFAULT_TENANT_ID) is not None
        assert repository.get_by_hash_across_tenants(key.key_hash) is not None
        assert repository.list_issued_by(key.id, DEFAULT_TENANT_ID) == []

        assert _row_factory_after(single_connection_pool) is tuple_row
    finally:
        with single_connection_pool.connection() as conn:
            conn.execute("DELETE FROM api_keys WHERE id = %s", (str(key.id),))


def test_the_event_repository_leaves_the_default_row_factory(
    single_connection_pool: ConnectionPool,
) -> None:
    repository = PostgresEventRepository(single_connection_pool)
    job = make_job()
    PostgresJobRepository(single_connection_pool).save(job)
    event = Event(
        id=EventId.from_string(str(uuid.uuid4())),
        aggregate_id=str(job.id),
        aggregate_type="Job",
        event_type="ProbeEvent",
        tenant_id=job.tenant_id,
        occurred_at=utc_now(),
        payload={},
    )
    try:
        repository.save(event)

        assert len(repository.list_by_aggregate(str(job.id), job.tenant_id)) == 1
        assert any(e.id == event.id for e in repository.list(job.tenant_id))

        assert _row_factory_after(single_connection_pool) is tuple_row
    finally:
        with single_connection_pool.connection() as conn:
            conn.execute("DELETE FROM events WHERE id = %s", (str(event.id),))
            conn.execute("DELETE FROM jobs WHERE id = %s", (str(job.id),))


def test_the_lease_repository_leaves_the_default_row_factory(
    single_connection_pool: ConnectionPool,
) -> None:
    """
    The reads change the connection before they run, so asking for ids
    that do not exist is enough to expose the leak.
    """
    repository = PostgresLeaseRepository(single_connection_pool)

    assert repository.get_by_job_id(JobId.new(), DEFAULT_TENANT_ID) is None
    assert (
        repository.get_by_worker_id(WorkerId.new(), DEFAULT_TENANT_ID)
        is None
    )
    repository.list_across_tenants()

    assert _row_factory_after(single_connection_pool) is tuple_row


def test_the_worker_repository_leaves_the_default_row_factory(
    single_connection_pool: ConnectionPool,
) -> None:
    """
    Needs a saved worker: the owning node is read inside _to_entity, which
    only runs when a worker row exists.
    """
    worker = make_worker()
    node_repository = PostgresNodeRepository(single_connection_pool)
    repository = PostgresWorkerRepository(single_connection_pool)
    try:
        node_repository.save(worker.node)
        repository.save(worker)

        assert repository.get_by_id(worker.id, worker.tenant_id) is not None
        assert repository.get_by_node_id(worker.node.id, worker.tenant_id) is not None
        assert any(w.id == worker.id for w in repository.list(worker.tenant_id))

        assert _row_factory_after(single_connection_pool) is tuple_row
    finally:
        with single_connection_pool.connection() as conn:
            conn.execute("DELETE FROM workers WHERE id = %s", (str(worker.id),))
            conn.execute("DELETE FROM nodes WHERE id = %s", (str(worker.node.id),))


def test_the_node_repository_leaves_the_default_row_factory(
    single_connection_pool: ConnectionPool,
) -> None:
    node = make_node()
    repository = PostgresNodeRepository(single_connection_pool)
    try:
        repository.save(node)

        assert any(n.id == node.id for n in repository.list(DEFAULT_TENANT_ID))
        assert repository.get_by_id(node.id, DEFAULT_TENANT_ID) is not None
        assert repository.get_by_id_across_tenants(node.id) is not None
        assert any(n.id == node.id for n in repository.list_across_tenants())
        repository.list_available_across_tenants()

        assert _row_factory_after(single_connection_pool) is tuple_row
    finally:
        with single_connection_pool.connection() as conn:
            conn.execute("DELETE FROM nodes WHERE id = %s", (str(node.id),))


def test_the_job_repository_leaves_the_default_row_factory(
    single_connection_pool: ConnectionPool,
) -> None:
    """
    Needs a saved job so that every read has a row to turn into an entity.
    """
    job = make_job()
    repository = PostgresJobRepository(single_connection_pool)
    try:
        repository.save(job)

        assert repository.get_by_id(job.id, DEFAULT_TENANT_ID) is not None
        assert repository.get_by_id_across_tenants(job.id) is not None
        assert any(j.id == job.id for j in repository.list_across_tenants())
        repository.list_queued(DEFAULT_TENANT_ID)
        repository.list_recent(10, DEFAULT_TENANT_ID)

        assert _row_factory_after(single_connection_pool) is tuple_row
    finally:
        with single_connection_pool.connection() as conn:
            conn.execute("DELETE FROM jobs WHERE id = %s", (str(job.id),))
