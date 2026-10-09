from __future__ import annotations

from app.application.services.list_nodes_service import (
    ListNodesService,
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


def test_list_nodes_service_returns_all_nodes() -> None:
    repository = InMemoryNodeRepository()

    node_one = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=4096,
        ),
    )

    node_two = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=32768,
            vram_mib=8192,
        ),
    )

    repository.save(node_one)
    repository.save(node_two)

    service = ListNodesService(
        node_repository=repository,
    )

    nodes = service.execute(DEFAULT_TENANT_ID)

    assert len(nodes) == 2
    assert node_one in nodes
    assert node_two in nodes
