from typing import Annotated
from uuid import UUID

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
from app.application.services.renew_lease_service import (
    RenewLeaseService,
)
from app.application.services.report_job_outcome_service import (
    ReportJobOutcomeService,
)
from app.application.services.start_job_service import (
    StartJobService,
)
from app.application.services.worker_heartbeat_service import (
    WorkerHeartbeatService,
)
from app.domain.enums.worker_management import WorkerManagement
from app.domain.exceptions.lease_not_found_error import (
    LeaseNotFoundError,
)
from app.domain.exceptions.no_active_lease_error import (
    NoActiveLeaseError,
)
from app.domain.exceptions.node_not_found_error import (
    NodeNotFoundError,
)
from app.domain.exceptions.worker_job_mismatch_error import (
    WorkerJobMismatchError,
)
from app.domain.exceptions.worker_not_found_error import (
    WorkerNotFoundError,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.worker_id import WorkerId
from app.presentation.auth import (
    require_api_key,
    require_rate_limit,
)
from app.presentation.dependencies import (
    get_create_worker_service,
    get_get_node_service,
    get_get_worker_service,
    get_list_workers_service,
    get_register_worker_service,
    get_renew_lease_service,
    get_report_job_outcome_service,
    get_start_job_service,
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
from app.presentation.schemas.report_job_outcome_request import (
    ReportJobOutcomeRequest,
)

router = APIRouter(
    prefix="/workers",
    tags=["Workers"],
    dependencies=[
        Depends(require_api_key),
        Depends(require_rate_limit),
    ],
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
        managed_by=WorkerManagement(request.managed_by),
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
            status=worker.running_job.status.name,
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
    "/{worker_id}/jobs/{job_id}/start",
    response_model=GetWorkerResponse,
)
def start_job(
    worker_id: str,
    job_id: str,
    service: Annotated[
        StartJobService,
        Depends(get_start_job_service),
    ],
) -> GetWorkerResponse:
    """
    Confirm that a worker has actually begun executing the
    job assigned to it, transitioning the job from SCHEDULED
    to RUNNING.

    This is the only thing that makes RUNNING true. Assignment
    alone does not: see AssignWorkerService.
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
        job_id_value = JobId(
            value=UUID(job_id),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Malformed job id.",
        ) from exc

    try:
        worker = service.execute(
            worker_id_value,
            job_id_value,
        )
    except WorkerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except WorkerJobMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    running_job = None

    if worker.running_job is not None:
        running_job = RunningJobResponse(
            id=str(worker.running_job.id),
            status=worker.running_job.status.name,
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
    "/{worker_id}/jobs/{job_id}/complete",
    response_model=GetWorkerResponse,
)
def complete_job(
    worker_id: str,
    job_id: str,
    request: ReportJobOutcomeRequest,
    service: Annotated[
        ReportJobOutcomeService,
        Depends(
            get_report_job_outcome_service,
        ),
    ],
) -> GetWorkerResponse:
    """
    Report that a job completed successfully.

    409 covers both WorkerJobMismatchError (worker does not
    hold this job) and NoActiveLeaseError/LeaseNotFoundError
    (reconciliation already reclaimed the lease), the same
    way renew_lease folds its own lease failures into 409:
    both mean the caller's view of who owns this job is
    stale, not that the request itself was malformed.
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
        job_id_value = JobId(
            value=UUID(job_id),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Malformed job id.",
        ) from exc

    try:
        worker = service.complete(
            worker_id_value,
            job_id_value,
            exit_code=request.exit_code,
        )
    except WorkerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except WorkerJobMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (NoActiveLeaseError, LeaseNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    running_job = None

    if worker.running_job is not None:
        running_job = RunningJobResponse(
            id=str(worker.running_job.id),
            status=worker.running_job.status.name,
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
    "/{worker_id}/jobs/{job_id}/fail",
    response_model=GetWorkerResponse,
)
def fail_job(
    worker_id: str,
    job_id: str,
    request: ReportJobOutcomeRequest,
    service: Annotated[
        ReportJobOutcomeService,
        Depends(
            get_report_job_outcome_service,
        ),
    ],
) -> GetWorkerResponse:
    """
    Report that a job failed.

    Raises the same exceptions as complete_job, for the same
    reasons.
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
        job_id_value = JobId(
            value=UUID(job_id),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Malformed job id.",
        ) from exc

    try:
        worker = service.fail(
            worker_id_value,
            job_id_value,
            exit_code=request.exit_code,
        )
    except WorkerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except WorkerJobMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (NoActiveLeaseError, LeaseNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    running_job = None

    if worker.running_job is not None:
        running_job = RunningJobResponse(
            id=str(worker.running_job.id),
            status=worker.running_job.status.name,
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
    "/{worker_id}/jobs/{job_id}/cancel",
    response_model=GetWorkerResponse,
)
def confirm_job_cancellation(
    worker_id: str,
    job_id: str,
    request: ReportJobOutcomeRequest,
    service: Annotated[
        ReportJobOutcomeService,
        Depends(
            get_report_job_outcome_service,
        ),
    ],
) -> GetWorkerResponse:
    """
    Confirm that a job's cancellation was actually applied to
    its subprocess (ADR 0029).

    Distinct from POST /jobs/{job_id}/cancel, which requests
    a cancellation. This endpoint is worker-scoped and
    reports that the request was carried out, the same way
    complete_job/fail_job report an outcome rather than
    request one.

    Raises the same exceptions as complete_job, for the same
    reasons.
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
        job_id_value = JobId(
            value=UUID(job_id),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Malformed job id.",
        ) from exc

    try:
        worker = service.cancel(
            worker_id_value,
            job_id_value,
            exit_code=request.exit_code,
        )
    except WorkerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except WorkerJobMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (NoActiveLeaseError, LeaseNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    running_job = None

    if worker.running_job is not None:
        running_job = RunningJobResponse(
            id=str(worker.running_job.id),
            status=worker.running_job.status.name,
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
    "/{worker_id}/lease/renew",
    response_model=GetWorkerResponse,
)
def renew_lease(
    worker_id: str,
    get_worker_service: Annotated[
        GetWorkerService,
        Depends(get_get_worker_service),
    ],
    renew_lease_service: Annotated[
        RenewLeaseService,
        Depends(get_renew_lease_service),
    ],
) -> GetWorkerResponse:
    """
    Renew the lease this worker holds on the job it's
    currently executing.

    Checks worker existence first (404), same layering as
    start_job, before enforcing the lease rule itself (409):
    RenewLeaseService has no worker-existence concept of its
    own, only lease existence, so checking here keeps 404 vs
    409 consistent across every worker-scoped endpoint rather
    than leaking that internal distinction to callers.
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

    worker = get_worker_service.execute(
        worker_id_value,
    )

    if worker is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Worker not found.",
        )

    try:
        renew_lease_service.execute(
            worker_id_value,
        )
    except (NoActiveLeaseError, LeaseNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    running_job = None

    if worker.running_job is not None:
        running_job = RunningJobResponse(
            id=str(worker.running_job.id),
            status=worker.running_job.status.name,
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
