from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.services.create_worker_service import (
    CreateWorkerService,
)
from app.application.services.get_node_service import (
    GetNodeService,
)
from app.application.services.register_worker_service import (
    RegisterWorkerService,
)
from app.domain.exceptions.node_not_found_error import (
    NodeNotFoundError,
)
from app.domain.value_objects.node_id import NodeId
from app.presentation.dependencies import (
    get_create_worker_service,
    get_get_node_service,
    get_register_worker_service,
)
from app.presentation.schemas.create_worker_request import (
    CreateWorkerRequest,
)
from app.presentation.schemas.create_worker_response import (
    CreateWorkerResponse,
)

router = APIRouter(
    prefix="/workers",
    tags=["Workers"],
)


@router.post(
    "",
    response_model=CreateWorkerResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_worker(
    request: CreateWorkerRequest,
    get_node_service: Annotated[
        GetNodeService,
        Depends(
            get_get_node_service,
        ),
    ],
    create_worker_service: Annotated[
        CreateWorkerService,
        Depends(
            get_create_worker_service,
        ),
    ],
    register_worker_service: Annotated[
        RegisterWorkerService,
        Depends(
            get_register_worker_service,
        ),
    ],
) -> CreateWorkerResponse:
    """
    Register a worker for an existing node.
    """

    try:
        node = get_node_service.execute(
            NodeId.from_string(
                request.node_id,
            ),
        )
    except NodeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Node not found.",
        ) from exc

    worker = create_worker_service.execute(
        node,
    )

    worker = register_worker_service.execute(
        worker,
    )

    return CreateWorkerResponse(
        id=str(worker.id),
        status=worker.status.name,
    )
