from __future__ import annotations

import pytest

from app.domain.entities.node import Node
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)

_CAPACITY = ResourceRequirements(cpu_cores=8, memory_mib=16384, vram_mib=2)


def test_a_node_cannot_be_built_without_available() -> None:
    with pytest.raises(TypeError, match="available"):
        Node(
            id=NodeId.new(),
            capacity=_CAPACITY,
            tenant_id=DEFAULT_TENANT_ID,
        )


def test_register_starts_a_node_fully_free() -> None:
    node = Node.register(
        id=NodeId.new(),
        capacity=_CAPACITY,
        tenant_id=DEFAULT_TENANT_ID,
    )

    assert node.available == _CAPACITY
    assert node.capacity == _CAPACITY


@pytest.mark.parametrize("name", [None, ""])
def test_register_generates_a_name_when_none_is_given(name) -> None:
    node = Node.register(
        id=NodeId.new(),
        capacity=_CAPACITY,
        tenant_id=DEFAULT_TENANT_ID,
        name=name,
    )

    assert node.name != ""


def test_register_keeps_a_supplied_name() -> None:
    node = Node.register(
        id=NodeId.new(),
        capacity=_CAPACITY,
        tenant_id=DEFAULT_TENANT_ID,
        name="gpu-01",
    )

    assert node.name == "gpu-01"
