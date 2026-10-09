from __future__ import annotations

import pytest

from app.application.services.get_node_service import (
    GetNodeService,
)
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.exceptions.node_not_found_error import (
    NodeNotFoundError,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)
from tests.support.nodes import make_node


def test_get_node_service_returns_existing_node() -> None:
    """
    Retrieving an existing compute node should
    return the matching node.
    """
    repository = InMemoryNodeRepository()

    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=4096,
        ),
    )

    repository.save(node)

    service = GetNodeService(
        node_repository=repository,
    )

    result = service.execute(node.id, DEFAULT_TENANT_ID)

    assert result is node


def test_get_node_service_raises_when_node_does_not_exist() -> None:
    """
    Retrieving a non-existent compute node should
    raise NodeNotFoundError.
    """
    repository = InMemoryNodeRepository()

    service = GetNodeService(
        node_repository=repository,
    )

    with pytest.raises(NodeNotFoundError):
        service.execute(NodeId.new(), DEFAULT_TENANT_ID)
