from __future__ import annotations

from typing import Any

from app.domain.entities.node import Node
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)


def make_node(**overrides: Any) -> Node:
    """
    Build a Node for a test.

    Every test node goes through here, so what a test node
    looks like by default is decided in one place. The
    defaults match the node repository contract tests: a new
    id and 8 cores, 16384 MiB of memory and 8192 MiB of VRAM.
    Any Node field can be overridden by keyword.
    """
    defaults: dict[str, Any] = {
        "id": NodeId.new(),
        "capacity": ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=8192,
        ),
    }
    defaults.update(overrides)

    return Node(**defaults)
