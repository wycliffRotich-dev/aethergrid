import pytest

from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from tests.support.nodes import make_node


def test_node_can_host_smaller_job() -> None:
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=65536,
            vram_mib=24576,
        ),
    )

    job_resources = ResourceRequirements(
        cpu_cores=4,
        memory_mib=8192,
        vram_mib=8192,
    )

    assert node.can_host(job_resources)


def test_node_rejects_large_job() -> None:
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=4,
            memory_mib=8192,
            vram_mib=4096,
        ),
    )

    job_resources = ResourceRequirements(
        cpu_cores=8,
        memory_mib=16384,
        vram_mib=8192,
    )

    assert not node.can_host(job_resources)


def test_node_allocates_resources() -> None:
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=65536,
            vram_mib=24576,
        ),
    )

    job_resources = ResourceRequirements(
        cpu_cores=4,
        memory_mib=8192,
        vram_mib=4096,
    )

    node.allocate(job_resources)

    assert node.available.cpu_cores == 12
    assert node.available.memory_mib == 57344
    assert node.available.vram_mib == 20480


def test_node_releases_resources() -> None:
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=16,
            memory_mib=65536,
            vram_mib=24576,
        ),
    )

    job_resources = ResourceRequirements(
        cpu_cores=4,
        memory_mib=8192,
        vram_mib=4096,
    )

    node.allocate(job_resources)
    node.release(job_resources)

    assert node.available.cpu_cores == 16
    assert node.available.memory_mib == 65536
    assert node.available.vram_mib == 24576


@pytest.mark.parametrize(
    ("dimension", "available"),
    [
        (
            "cpu_cores",
            ResourceRequirements(cpu_cores=9, memory_mib=16384, vram_mib=8192),
        ),
        (
            "memory_mib",
            ResourceRequirements(cpu_cores=8, memory_mib=16385, vram_mib=8192),
        ),
        (
            "vram_mib",
            ResourceRequirements(cpu_cores=8, memory_mib=16384, vram_mib=8193),
        ),
    ],
)
def test_node_rejects_available_above_capacity(
    dimension: str,
    available: ResourceRequirements,
) -> None:
    with pytest.raises(
        ValueError,
        match=f"available {dimension} cannot exceed capacity",
    ):
        make_node(
            id=NodeId.new(),
            capacity=ResourceRequirements(
                cpu_cores=8,
                memory_mib=16384,
                vram_mib=8192,
            ),
            available=available,
        )


def test_node_rejects_available_vram_on_zero_vram_capacity() -> None:
    """
    The case that makes Scheduler._fit_score divide by zero: a
    node with no VRAM that claims free VRAM would pass can_host
    for a VRAM job and then be scored against a zero capacity.
    """
    with pytest.raises(
        ValueError,
        match="available vram_mib cannot exceed capacity",
    ):
        make_node(
            id=NodeId.new(),
            capacity=ResourceRequirements(
                cpu_cores=8,
                memory_mib=16384,
                vram_mib=0,
            ),
            available=ResourceRequirements(
                cpu_cores=8,
                memory_mib=16384,
                vram_mib=1,
            ),
        )


def test_node_accepts_partially_allocated_available() -> None:
    """
    Repositories rebuild a node from storage with its true,
    partially allocated available capacity. That path must keep
    working, including a fully used dimension at zero.
    """
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=8192,
        ),
        available=ResourceRequirements(
            cpu_cores=3,
            memory_mib=1024,
            vram_mib=0,
        ),
    )

    assert node.available.cpu_cores == 3
    assert node.available.memory_mib == 1024
    assert node.available.vram_mib == 0
