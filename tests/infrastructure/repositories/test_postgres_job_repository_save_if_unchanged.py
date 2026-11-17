from __future__ import annotations

import copy
import threading
import time
import uuid

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from app.domain.entities.tenant import DEFAULT_TENANT_ID, Tenant
from app.domain.enums.job_status import JobStatus
from app.domain.value_objects.node_id import NodeId
from app.infrastructure.repositories.postgres_job_repository import (
    PostgresJobRepository,
)
from app.infrastructure.repositories.postgres_node_repository import (
    PostgresNodeRepository,
)
from app.infrastructure.repositories.postgres_tenant_repository import (
    PostgresTenantRepository,
)
from tests.infrastructure.repositories.contract.job_repository_save_if_unchanged_contract import (
    JobRepositorySaveIfUnchangedContract,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node


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


class TestPostgresJobRepositorySaveIfUnchanged(
    JobRepositorySaveIfUnchangedContract
):
    @pytest.fixture
    def repository(self, pool):
        with pool.connection() as conn:
            conn.execute("TRUNCATE jobs, nodes CASCADE")
        return PostgresJobRepository(pool)

    @pytest.fixture
    def node_id(
        self,
        repository: PostgresJobRepository,
        pool: ConnectionPool,
    ) -> NodeId:
        node = make_node()
        PostgresNodeRepository(pool).save(node)
        return node.id

    @pytest.fixture
    def second_node_id(
        self,
        repository: PostgresJobRepository,
        pool: ConnectionPool,
    ) -> NodeId:
        node = make_node()
        PostgresNodeRepository(pool).save(node)
        return node.id

    @pytest.fixture
    def second_tenant_id(self, pool):
        tenant = Tenant.create(f"t-{uuid.uuid4().hex[:8]}")
        PostgresTenantRepository(pool).save(tenant)

        yield tenant.id

        with pool.connection() as conn:
            conn.execute("TRUNCATE jobs, nodes CASCADE")
            conn.execute(
                "DELETE FROM tenants WHERE id = %s",
                (str(tenant.id),),
            )

    def test_concurrent_completion_blocks_and_refuses_stale_cancel_write(
        self,
        repository: PostgresJobRepository,
        node_id: NodeId,
        test_database_url: str,
    ) -> None:
        job = make_job()
        job.queue()
        job.assign_to(node_id)
        job.start()
        repository.save(job)

        expected = copy.deepcopy(job)
        stale_cancel = copy.deepcopy(expected)
        stale_cancel.request_cancellation()

        results: list[bool] = []
        errors: list[BaseException] = []

        def run_fenced_cancel() -> None:
            try:
                results.append(
                    repository.save_if_unchanged(
                        stale_cancel,
                        expected,
                    )
                )
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        with psycopg.connect(test_database_url, autocommit=False) as conn_b:
            conn_b.execute(
                "UPDATE jobs SET status = %s, exit_code = 0 WHERE id = %s",
                (JobStatus.COMPLETED.value, str(job.id)),
            )

            waiter = threading.Thread(target=run_fenced_cancel)
            waiter.start()

            with psycopg.connect(
                test_database_url,
                autocommit=True,
            ) as observer:
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline:
                    waiting = observer.execute(
                        "SELECT 1 FROM pg_locks WHERE NOT granted"
                    ).fetchone()
                    if waiting is not None:
                        break
                    time.sleep(0.02)
                assert waiting is not None, (
                    "save_if_unchanged never blocked on the uncommitted row lock"
                )

            conn_b.commit()
            waiter.join(timeout=5.0)
            assert not waiter.is_alive()

        assert errors == []
        assert results == [False]
        fetched = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
        assert fetched is not None
        assert fetched.status == JobStatus.COMPLETED
        assert fetched.cancellation_requested_at is None
        assert fetched.exit_code == 0
