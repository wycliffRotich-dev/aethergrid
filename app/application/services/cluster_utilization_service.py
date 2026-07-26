from __future__ import annotations

from app.domain.repositories.node_repository import (
    NodeRepository,
)
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)


class ClusterUtilizationService:
    """
    Application service responsible for reporting
    the total allocated resources in the cluster.
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
        Return the total allocated resources across every
        registered node.

        Previously this excluded offline nodes, so jobs still
        genuinely occupying a node that had gone unreachable
        stopped counting as utilization at all. Paired with
        the same exclusion in ClusterCapacityService, this is
        what produced the misleading 100% utilization spike:
        both the numerator and denominator shrank together
        the moment a node dropped offline.
        """
        cpu_cores = 0
        memory_mib = 0
        vram_mib = 0

        for node in self._node_repository.list():
            cpu_cores += node.capacity.cpu_cores - node.available.cpu_cores

            memory_mib += node.capacity.memory_mib - node.available.memory_mib

            vram_mib += node.capacity.vram_mib - node.available.vram_mib

        return ResourceRequirements(
            cpu_cores=cpu_cores,
            memory_mib=memory_mib,
            vram_mib=vram_mib,
        )
