from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.services.create_node_service import (
    CreateNodeService,
)
from app.application.services.get_node_service import (
    GetNodeService,
)
from app.application.services.heartbeat_node_service import (
    HeartbeatNodeService,
)
from app.application.services.list_nodes_service import (
    ListNodesService,
)
from app.application.services.list_offline_nodes_service import (
    ListOfflineNodesService,
)
from app.domain.exceptions.node_not_found_error import (
    NodeNotFoundError,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.presentation.dependencies import (
    get_create_node_service,
    get_get_node_service,
    get_heartbeat_node_service,
    get_list_nodes_service,
    get_list_offline_nodes_service,
)
from app.presentation.schemas.create_node_request import (
    CreateNodeRequest,
)
from app.presentation.schemas.create_node_response import (
    CreateNodeResponse,
)
from app.presentation.schemas.get_node_response import (
    GetNodeResponse,
)
from app.presentation.schemas.list_nodes_response import (
    ListNodesResponse,
    NodeResponse,
)

router = APIRouter(
    prefix="/nodes",
    tags=["Nodes"],
)


@router.post(
    "",
    response_model=CreateNodeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_node(
    request: CreateNodeRequest,
    service: Annotated[
        CreateNodeService,
        Depends(get_create_node_service),
    ],
) -> CreateNodeResponse:
    """
    Create a new compute node.
    """
    capacity = ResourceRequirements(
        cpu_cores=request.cpu_cores,
        memory_mib=request.memory_mib,
        vram_mib=request.vram_mib,
    )

    node = service.execute(capacity, name=request.name)

    return CreateNodeResponse(
        id=str(node.id),
    )


@router.get(
    "",
    response_model=ListNodesResponse,
)
def list_nodes(
    service: Annotated[
        ListNodesService,
        Depends(get_list_nodes_service),
    ],
) -> ListNodesResponse:
    """
    Return all registered compute nodes, regardless of
    whether they are currently alive. Health is exposed
    per-node via is_alive rather than by omitting nodes
    that have missed a heartbeat, so a caller can always
    tell the difference between "no nodes registered" and
    "a registered node has gone offline".
    """
    nodes = service.execute()

    return ListNodesResponse(
        nodes=[
            NodeResponse(
                id=str(node.id),
                cpu_cores=node.capacity.cpu_cores,
                memory_mib=node.capacity.memory_mib,
                vram_mib=node.capacity.vram_mib,
                available_cpu_cores=node.available.cpu_cores,
                available_memory_mib=node.available.memory_mib,
                available_vram_mib=node.available.vram_mib,
                is_alive=node.is_alive(),
            )
            for node in nodes
        ]
    )


@router.get(
    "/offline",
    response_model=ListNodesResponse,
)
def list_offline_nodes(
    service: Annotated[
        ListOfflineNodesService,
        Depends(get_list_offline_nodes_service),
    ],
) -> ListNodesResponse:
    """
    Return all compute nodes that have missed their
    heartbeat and are considered offline.
    """
    nodes = service.execute()

    return ListNodesResponse(
        nodes=[
            NodeResponse(
                id=str(node.id),
                cpu_cores=node.capacity.cpu_cores,
                memory_mib=node.capacity.memory_mib,
                vram_mib=node.capacity.vram_mib,
                available_cpu_cores=node.available.cpu_cores,
                available_memory_mib=node.available.memory_mib,
                available_vram_mib=node.available.vram_mib,
                is_alive=node.is_alive(),
            )
            for node in nodes
        ]
    )


@router.get(
    "/{node_id}",
    response_model=GetNodeResponse,
)
def get_node(
    node_id: str,
    service: Annotated[
        GetNodeService,
        Depends(get_get_node_service),
    ],
) -> GetNodeResponse:
    """
    Retrieve a compute node by its identifier.
    """
    try:
        node = service.execute(
            NodeId.from_string(node_id),
        )
    except NodeNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Node not found.",
        ) from err

    return GetNodeResponse(
        id=str(node.id),
        cpu_cores=node.capacity.cpu_cores,
        memory_mib=node.capacity.memory_mib,
        vram_mib=node.capacity.vram_mib,
        available_cpu_cores=node.available.cpu_cores,
        available_memory_mib=node.available.memory_mib,
        available_vram_mib=node.available.vram_mib,
        is_alive=node.is_alive(),
    )


@router.post(
    "/{node_id}/heartbeat",
    response_model=GetNodeResponse,
)
def heartbeat_node(
    node_id: str,
    service: Annotated[
        HeartbeatNodeService,
        Depends(get_heartbeat_node_service),
    ],
) -> GetNodeResponse:
    """
    Record a heartbeat for a compute node, keeping
    it alive so it remains eligible for scheduling.
    """
    node = service.execute(
        NodeId.from_string(node_id),
    )

    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Node not found.",
        )

    return GetNodeResponse(
        id=str(node.id),
        cpu_cores=node.capacity.cpu_cores,
        memory_mib=node.capacity.memory_mib,
        vram_mib=node.capacity.vram_mib,
        available_cpu_cores=node.available.cpu_cores,
        available_memory_mib=node.available.memory_mib,
        available_vram_mib=node.available.vram_mib,
        is_alive=node.is_alive(),
    )
