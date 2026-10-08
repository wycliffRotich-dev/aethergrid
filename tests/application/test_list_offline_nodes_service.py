from datetime import UTC, datetime, timedelta

from app.application.services.list_offline_nodes_service import (
    ListOfflineNodesService,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)
from tests.support.nodes import make_node


def test_list_offline_nodes_service_returns_only_offline_nodes() -> None:
    """
    Only offline nodes should be returned.
    """

    healthy = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=16384,
        ),
    )

    offline = make_node(
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
            healthy,
            offline,
        ],
    )

    service = ListOfflineNodesService(
        repository,
    )

    nodes = service.execute()

    assert offline in nodes
    assert healthy not in nodes
