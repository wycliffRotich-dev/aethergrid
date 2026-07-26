from datetime import UTC, datetime, timedelta

from app.application.services.cluster_capacity_service import (
    ClusterCapacityService,
)
from app.domain.entities.node import Node
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)


def test_cluster_capacity_sums_available_resources() -> None:
    """
    Cluster capacity should be the sum of the
    available resources across all nodes.
    """

    node1 = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=8192,
            vram_mib=4096,
        ),
    )

    node2 = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=16384,
            vram_mib=8192,
        ),
    )

    repository = InMemoryNodeRepository(
        [
            node1,
            node2,
        ],
    )

    service = ClusterCapacityService(
        repository,
    )

    capacity = service.execute()

    assert capacity.cpu_cores == 24
    assert capacity.memory_mib == 24576
    assert capacity.vram_mib == 12288


def test_cluster_capacity_includes_offline_nodes() -> None:
    """
    A node that has missed its heartbeat must still
    contribute its capacity to the cluster total.
    Excluding it here silently shrinks the denominator
    a utilization percentage is computed against, making
    the remaining alive nodes appear to spike toward 100%
    for no real reason.
    """

    alive = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=8192,
            vram_mib=4096,
        ),
    )

    offline = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=16384,
            vram_mib=8192,
        ),
    )
    offline.last_seen_at = datetime.now(UTC) - timedelta(minutes=2)

    repository = InMemoryNodeRepository(
        [
            alive,
            offline,
        ],
    )

    service = ClusterCapacityService(
        repository,
    )

    capacity = service.execute()

    assert capacity.cpu_cores == 24
    assert capacity.memory_mib == 24576
    assert capacity.vram_mib == 12288
