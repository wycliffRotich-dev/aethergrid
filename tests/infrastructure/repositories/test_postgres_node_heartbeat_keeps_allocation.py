from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import pytest
from psycopg_pool import ConnectionPool

from app.application.services.heartbeat_node_service import (
    HeartbeatNodeService,
)
from app.domain.entities.node import Node, utc_now
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.postgres_node_repository import (
    PostgresNodeRepository,
)
from tests.support.nodes import make_node


@pytest.fixture(scope="module")
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


class _StaleReadRepository(PostgresNodeRepository):
    """
    A repository whose reads are followed by another writer's
    change, the way a heartbeat request's read can be followed by
    the scheduler's allocation on another thread.
    """

    def __init__(
        self,
        pool: ConnectionPool,
        after_read: Callable[[], None],
    ) -> None:
        super().__init__(pool)
        self._after_read = after_read

    def get_by_id(
        self,
        node_id: NodeId,
        tenant_id,
    ) -> Node | None:
        node = super().get_by_id(node_id, tenant_id)
        self._after_read()
        return node


def test_heartbeat_does_not_erase_a_concurrent_allocation(pool) -> None:
    """
    A heartbeat only says the node is alive. If the scheduler
    allocates capacity on the node while a heartbeat request is
    in flight, the heartbeat must not write the node's old
    capacity figures back over that allocation, because the node
    would then offer capacity that is already promised. Both
    writers use their own repository instance, so nothing is
    shared in memory, and the result is read back through a third.
    """
    with pool.connection() as conn:
        conn.execute("TRUNCATE nodes CASCADE")

    capacity = ResourceRequirements(
        cpu_cores=8,
        memory_mib=16384,
        vram_mib=0,
    )
    allocated = ResourceRequirements(
        cpu_cores=1,
        memory_mib=512,
        vram_mib=0,
    )

    node = make_node(id=NodeId.new(), capacity=capacity)
    old_seen_at = utc_now() - timedelta(seconds=30)
    node.last_seen_at = old_seen_at
    PostgresNodeRepository(pool).save(node)

    scheduler_repository = PostgresNodeRepository(pool)
    allocation_done = False

    def scheduler_allocates() -> None:
        nonlocal allocation_done
        if allocation_done:
            return
        allocation_done = True
        current = scheduler_repository.get_by_id(
            node.id, DEFAULT_TENANT_ID
        )
        assert current is not None
        current.allocate(allocated)
        scheduler_repository.save(current)

    heartbeat_repository = _StaleReadRepository(
        pool, scheduler_allocates
    )

    HeartbeatNodeService(heartbeat_repository).execute(
        node.id, DEFAULT_TENANT_ID
    )

    # If the service never read the node, the allocation has not
    # happened yet, so it happens now, after the heartbeat.
    scheduler_allocates()

    reloaded = PostgresNodeRepository(pool).get_by_id(
        node.id, DEFAULT_TENANT_ID
    )

    assert reloaded is not None
    assert reloaded.last_seen_at > old_seen_at
    assert reloaded.available.cpu_cores == 7
    assert reloaded.available.memory_mib == 15872
