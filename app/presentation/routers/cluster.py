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
from app.domain.entities.api_key import ApiKey
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
    caller: Annotated[ApiKey, Depends(require_api_key)],
) -> ClusterHealthResponse:
    """
    Return a summary of cluster health for the caller's
    tenant: total nodes, how many are alive, and how many
    are offline.
    """
    health = service.execute(caller.tenant_id)

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
    caller: Annotated[ApiKey, Depends(require_api_key)],
) -> ClusterCapacityResponse:
    """
    Return the total available resources across the
    compute nodes in the caller's tenant.
    """
    capacity = service.execute(caller.tenant_id)

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
    caller: Annotated[ApiKey, Depends(require_api_key)],
) -> ClusterUtilizationResponse:
    """
    Return the total allocated (in-use) resources
    across the compute nodes in the caller's tenant.
    """
    utilization = service.execute(caller.tenant_id)

    return ClusterUtilizationResponse(
        cpu_cores=utilization.cpu_cores,
        memory_mib=utilization.memory_mib,
        vram_mib=utilization.vram_mib,
    )
