from __future__ import annotations

from app.application.services.create_node_service import (
    CreateNodeService,
)
from app.domain.entities.node import Node
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)


def test_create_node_service_creates_and_persists_node() -> None:
    """
    Creating a node should persist it in the repository.
    """
    repository = InMemoryNodeRepository()

    service = CreateNodeService(
        node_repository=repository,
    )

    capacity = ResourceRequirements(
        cpu_cores=8,
        memory_mib=16384,
        vram_mib=4096,
    )

    tenant_id = TenantId.new()

    node = service.execute(capacity, tenant_id)

    assert isinstance(node, Node)

    stored = repository.get_by_id(node.id, tenant_id)

    assert stored is node
    assert stored.capacity == capacity
    assert stored.available == capacity
    assert stored.tenant_id == tenant_id


def test_create_node_service_keeps_the_tenant_on_a_named_node() -> None:
    """
    The named and unnamed paths build the node separately, so
    each one must carry the tenant it was given (ADR 0064).
    """
    repository = InMemoryNodeRepository()
    service = CreateNodeService(node_repository=repository)
    tenant_id = TenantId.new()

    node = service.execute(
        ResourceRequirements(
            cpu_cores=2,
            memory_mib=4096,
            vram_mib=0,
        ),
        tenant_id,
        name="gpu-box-1",
    )

    stored = repository.get_by_id(node.id, tenant_id)

    assert stored is not None
    assert stored.name == "gpu-box-1"
    assert stored.tenant_id == tenant_id
