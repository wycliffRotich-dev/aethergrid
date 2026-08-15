from typing import Annotated

from fastapi import APIRouter, Depends

from app.application.services.cluster_capacity_service import (
    ClusterCapacityService,
)
from app.application.services.cluster_health_service import (
    ClusterHealthService,
)
from app.application.services.cluster_utilization_service import (
    ClusterUtilizationService,
)
from app.presentation.auth import (
    require_api_key,
    require_rate_limit,
)
from app.presentation.dependencies import (
    get_cluster_capacity_service,
    get_cluster_health_service,
    get_cluster_utilization_service,
)
from app.presentation.schemas.cluster_capacity_response import (
    ClusterCapacityResponse,
)
from app.presentation.schemas.cluster_health_response import (
    ClusterHealthResponse,
)
from app.presentation.schemas.cluster_utilization_response import (
    ClusterUtilizationResponse,
)

router = APIRouter(
    prefix="/cluster",
    tags=["Cluster"],
    dependencies=[
        Depends(require_api_key),
        Depends(require_rate_limit),
    ],
)


@router.get(
    "/health",
    response_model=ClusterHealthResponse,
)
def get_cluster_health(
    service: Annotated[
        ClusterHealthService,
        Depends(get_cluster_health_service),
    ],
) -> ClusterHealthResponse:
    """
    Return a summary of cluster health: total nodes,
    how many are alive, and how many are offline.
    """
    health = service.execute()

    return ClusterHealthResponse(
        total_nodes=health.total_nodes,
        alive_nodes=health.alive_nodes,
        offline_nodes=health.offline_nodes,
    )


@router.get(
    "/capacity",
    response_model=ClusterCapacityResponse,
)
def get_cluster_capacity(
    service: Annotated[
        ClusterCapacityService,
        Depends(get_cluster_capacity_service),
    ],
) -> ClusterCapacityResponse:
    """
    Return the total available resources across all
    alive compute nodes in the cluster.
    """
    capacity = service.execute()

    return ClusterCapacityResponse(
        cpu_cores=capacity.cpu_cores,
        memory_mib=capacity.memory_mib,
        vram_mib=capacity.vram_mib,
    )


@router.get(
    "/utilization",
    response_model=ClusterUtilizationResponse,
)
def get_cluster_utilization(
    service: Annotated[
        ClusterUtilizationService,
        Depends(get_cluster_utilization_service),
    ],
) -> ClusterUtilizationResponse:
    """
    Return the total allocated (in-use) resources
    across all alive compute nodes in the cluster.
    """
    utilization = service.execute()

    return ClusterUtilizationResponse(
        cpu_cores=utilization.cpu_cores,
        memory_mib=utilization.memory_mib,
        vram_mib=utilization.vram_mib,
    )
