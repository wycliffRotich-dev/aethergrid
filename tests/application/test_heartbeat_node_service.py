from app.application.services.heartbeat_node_service import (
    HeartbeatNodeService,
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


def test_heartbeat_node_service_updates_last_seen_at() -> None:
    """
    A heartbeat should update the node's
    last seen timestamp.
    """

    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=16384,
        ),
    )

    before = node.last_seen_at

    repository = InMemoryNodeRepository(
        [
            node,
        ],
    )

    service = HeartbeatNodeService(
        repository,
    )

    service.execute(
        node.id,
        DEFAULT_TENANT_ID,
    )

    assert node.last_seen_at > before
