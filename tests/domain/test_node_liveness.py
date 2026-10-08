from datetime import UTC, datetime, timedelta

from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from tests.support.nodes import make_node


def test_node_is_alive_when_recently_seen() -> None:
    """
    A node with a recent heartbeat is alive.
    """

    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=16384,
        ),
    )

    assert node.is_alive()


def test_node_is_not_alive_when_heartbeat_is_stale() -> None:
    """
    A node whose heartbeat is too old
    is considered offline.
    """

    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=16384,
        ),
    )

    node.last_seen_at = datetime.now(UTC) - timedelta(minutes=2)

    assert not node.is_alive()
