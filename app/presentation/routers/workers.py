from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.services.create_worker_service import (
    CreateWorkerService,
)
from app.application.services.get_node_service import (
    GetNodeService,
)
from app.application.services.get_worker_service import (
    GetWorkerService,
)
from app.application.services.list_workers_service import (
    ListWorkersService,
)
from app.application.services.register_worker_service import (
    RegisterWorkerService,
)
from app.application.services.worker_heartbeat_service import (
    WorkerHeartbeatService,
)
from app.domain.exceptions.node_not_found_error import (
    NodeNotFoundError,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.worker_id import WorkerId
from app.presentation.auth import require_api_key
from app.presentation.dependencies import (
    get_create_worker_service,
    get_get_node_service,
    get_get_worker_service,
    get_list_workers_service,
    get_register_worker_service,
    get_worker_heartbeat_service,
)
from app.presentation.schemas.create_worker_request import (
    CreateWorkerRequest,
)
from app.presentation.schemas.create_worker_response import (
    CreateWorkerResponse,
)
from app.presentation.schemas.get_worker_response import (
    GetWorkerResponse,
    RunningJobResponse,
)
from app.presentation.schemas.list_workers_response import (
    ListWorkersResponse,
    WorkerSummaryResponse,
)

router = APIRouter(
    prefix="/workers",
    tags=["Workers"],
    dependencies=[Depends(require_api_key)],
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


@router.get(
    "",
    response_model=ListWorkersResponse,
)
def list_workers(
    service: Annotated[
        ListWorkersService,
        Depends(get_list_workers_service),
    ],
) -> ListWorkersResponse:
    """
    Return every registered worker.
    """
    workers = service.execute()

    return ListWorkersResponse(
        workers=[
            WorkerSummaryResponse(
                id=str(worker.id),
                status=worker.status.name,
                node_id=str(worker.node.id),
                running_job_id=(
                    str(worker.running_job.id)
                    if worker.running_job is not None
                    else None
                ),
                last_seen_at=worker.last_seen_at,
            )
            for worker in workers
        ]
    )


@router.get(
    "/{worker_id}",
    response_model=GetWorkerResponse,
)
def get_worker(
    worker_id: str,
    service: Annotated[
        GetWorkerService,
        Depends(get_get_worker_service),
    ],
) -> GetWorkerResponse:
    """
    Retrieve a single worker, including the job currently
    assigned to it, if any.

    running_job.command is only ever exposed here, never
    through GetJobResponse or ListJobsResponse, per ADR 0020:
    only the worker actually assigned a job may read the
    command it needs to execute.
    """
    try:
        worker_id_value = WorkerId(
            worker_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Malformed worker id.",
        ) from exc

    worker = service.execute(
        worker_id_value,
    )

    if worker is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Worker not found.",
        )

    running_job = None

    if worker.running_job is not None:
        running_job = RunningJobResponse(
            id=str(worker.running_job.id),
            command=worker.running_job.command,
            execution_timeout_seconds=(
                worker.running_job.execution_timeout.total_seconds()
            ),
        )

    return GetWorkerResponse(
        id=str(worker.id),
        status=worker.status.name,
        node_id=str(worker.node.id),
        last_seen_at=worker.last_seen_at,
        running_job=running_job,
    )


@router.post(
    "/{worker_id}/heartbeat",
    response_model=CreateWorkerResponse,
)
def heartbeat_worker(
    worker_id: str,
    service: Annotated[
        WorkerHeartbeatService,
        Depends(get_worker_heartbeat_service),
    ],
) -> CreateWorkerResponse:
    """
    Record a heartbeat for a worker, keeping it alive so it
    is not marked OFFLINE by the cluster's dead-worker sweep.
    """
    try:
        worker_id_value = WorkerId(
            worker_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Malformed worker id.",
        ) from exc

    try:
        worker = service.execute(
            worker_id_value,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Worker not found.",
        ) from exc

    return CreateWorkerResponse(
        id=str(worker.id),
        status=worker.status.name,
    )
