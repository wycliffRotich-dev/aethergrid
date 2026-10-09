from datetime import UTC, datetime, timedelta

from app.application.services.cluster_utilization_service import (
    ClusterUtilizationService,
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


def test_cluster_utilization_reports_allocated_resources() -> None:
    """
    Cluster utilization should report
    allocated resources.
    """

    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=8192,
            vram_mib=4096,
        ),
    )

    node.allocate(
        ResourceRequirements(
            cpu_cores=2,
            memory_mib=2048,
            vram_mib=1024,
        ),
    )

    repository = InMemoryNodeRepository(
        [
            node,
        ],
    )

    service = ClusterUtilizationService(
        repository,
    )

    utilization = service.execute(DEFAULT_TENANT_ID)

    assert utilization.cpu_cores == 2
    assert utilization.memory_mib == 2048
    assert utilization.vram_mib == 1024


def test_cluster_utilization_includes_offline_nodes() -> None:
    """
    A job still occupying a node that has gone offline is
    still real, ongoing utilization. Excluding the node here
    made that allocation vanish from the total the moment its
    heartbeat lapsed, understating true cluster usage.
    """

    alive = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=8192,
            vram_mib=4096,
        ),
    )
    alive.allocate(
        ResourceRequirements(
            cpu_cores=2,
            memory_mib=2048,
            vram_mib=1024,
        ),
    )

    offline = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=16384,
            vram_mib=8192,
        ),
    )
    offline.allocate(
        ResourceRequirements(
            cpu_cores=3,
            memory_mib=3072,
            vram_mib=2048,
        ),
    )
    offline.last_seen_at = datetime.now(UTC) - timedelta(minutes=2)

    repository = InMemoryNodeRepository(
        [
            alive,
            offline,
        ],
    )

    service = ClusterUtilizationService(
        repository,
    )

    utilization = service.execute(DEFAULT_TENANT_ID)

    assert utilization.cpu_cores == 5
    assert utilization.memory_mib == 5120
    assert utilization.vram_mib == 3072
