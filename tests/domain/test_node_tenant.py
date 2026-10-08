from __future__ import annotations

import pytest

from app.domain.entities.node import Node
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.tenant_id import TenantId
from tests.support.nodes import make_node


def test_a_node_carries_the_tenant_it_is_built_with() -> None:
    tenant_id = TenantId.new()

    node = make_node(tenant_id=tenant_id)

    assert node.tenant_id == tenant_id


def test_make_node_defaults_to_the_default_tenant() -> None:
    assert make_node().tenant_id == DEFAULT_TENANT_ID


def test_a_node_cannot_be_built_without_a_tenant() -> None:
    with pytest.raises(TypeError):
        Node(
            id=NodeId.new(),
            capacity=ResourceRequirements(
                cpu_cores=8,
                memory_mib=16384,
                vram_mib=0,
            ),
        )
