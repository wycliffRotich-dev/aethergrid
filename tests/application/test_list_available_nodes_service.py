from datetime import UTC, datetime, timedelta

from app.application.services.list_nodes_service import (
    ListNodesService,
)
from app.domain.entities.node import Node
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)


def test_list_nodes_returns_alive_and_offline_nodes() -> None:
    """
    Every registered node should be returned regardless of
    whether it is currently alive. An offline node must still
    appear here so callers (and the dashboard) can tell the
    difference between "not registered" and "registered but
    unhealthy" -- filtering offline nodes out of this list was
    the bug that made the node table report zero nodes while
    the cluster health summary correctly reported one node,
    offline, at the same time.
    """

    alive = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=16384,
        ),
    )

    offline = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=16384,
        ),
    )

    offline.last_seen_at = datetime.now(UTC) - timedelta(minutes=2)

    repository = InMemoryNodeRepository(
        [
            alive,
            offline,
        ],
    )

    service = ListNodesService(
        repository,
    )

    nodes = service.execute()

    assert alive in nodes
    assert offline in nodes
