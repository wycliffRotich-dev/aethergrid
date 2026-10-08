from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from tests.support.nodes import make_node


def test_node_can_store_labels() -> None:
    """
    A node should expose arbitrary labels.
    """

    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=8192,
        ),
    )

    node.labels["gpu"] = "true"
    node.labels["region"] = "eu-west"

    assert node.labels["gpu"] == "true"
    assert node.labels["region"] == "eu-west"
