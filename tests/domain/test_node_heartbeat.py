from datetime import UTC, datetime

from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from tests.support.nodes import make_node


def test_node_heartbeat_updates_last_seen_at() -> None:
    """
    A heartbeat updates the node's last seen timestamp.
    """

    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=16384,
        ),
    )

    before = datetime.now(UTC)

    node.heartbeat()

    assert node.last_seen_at >= before
