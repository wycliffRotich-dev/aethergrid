from app.application.services.cluster_health_service import (
    ClusterHealthService,
)
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)
from tests.support.nodes import make_node


def test_cluster_health_reports_alive_and_offline_nodes() -> None:
    """
    Cluster health should report the number
    of alive and offline nodes.
    """

    node1 = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=8192,
            vram_mib=4096,
        ),
    )

    node2 = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=8192,
            vram_mib=4096,
        ),
    )

    node2.last_seen_at = node2.last_seen_at.replace(
        year=node2.last_seen_at.year - 1,
    )

    repository = InMemoryNodeRepository(
        [
            node1,
            node2,
        ],
    )

    service = ClusterHealthService(
        repository,
    )

    health = service.execute(DEFAULT_TENANT_ID)

    assert health.total_nodes == 2
    assert health.alive_nodes == 1
    assert health.offline_nodes == 1
