from __future__ import annotations

from app.domain.repositories.node_repository import (
    NodeRepository,
)
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)


class ClusterCapacityService:
    """
    Application service responsible for reporting
    the total available capacity of the cluster.
    """

    def __init__(
        self,
        node_repository: NodeRepository,
    ) -> None:
        self._node_repository = node_repository

    def execute(
        self,
    ) -> ResourceRequirements:
        """
        Return the total available resources across every
        registered node.

        Previously this excluded any node that had missed its
        heartbeat, which meant an offline node's committed
        capacity silently vanished from the cluster total
        rather than being reported as unavailable. That shrank
        the denominator a percentage is computed against, so a
        node going offline could make the remaining, genuinely
        healthy nodes appear to spike toward 100% utilization
        even though nothing about real usage changed. Node
        health is already communicated honestly elsewhere
        (ClusterHealthService, is_alive on each node); this
        total should reflect capacity the cluster actually
        owns, not just what is currently reachable.
        """
        cpu_cores = 0
        memory_mib = 0
        vram_mib = 0

        for node in self._node_repository.list():
            cpu_cores += node.available.cpu_cores
            memory_mib += node.available.memory_mib
            vram_mib += node.available.vram_mib

        return ResourceRequirements(
            cpu_cores=cpu_cores,
            memory_mib=memory_mib,
            vram_mib=vram_mib,
        )
