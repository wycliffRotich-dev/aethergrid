from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.services.cancel_job_service import (
    CancelJobService,
)
from app.application.services.create_job_service import (
    CreateJobService,
)
from app.application.services.get_job_history_service import (
    GetJobHistoryService,
)
from app.application.services.get_job_service import (
    GetJobService,
)
from app.application.services.list_jobs_service import (
    ListJobsService,
)
from app.application.services.list_queued_jobs_service import (
    ListQueuedJobsService,
)
from app.application.services.retry_job_service import (
    RetryJobService,
)
from app.domain.exceptions.invalid_job_transition import (
    InvalidJobTransition,
)
from app.domain.exceptions.job_not_found_error import (
    JobNotFoundError,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.presentation.auth import (
    require_api_key,
    require_rate_limit,
)
from app.presentation.dependencies import (
    get_cancel_job_service,
    get_create_job_service,
    get_get_job_history_service,
    get_get_job_service,
    get_list_jobs_service,
    get_list_queued_jobs_service,
    get_retry_job_service,
)
from app.presentation.schemas.create_job_request import (
    CreateJobRequest,
)
from app.presentation.schemas.create_job_response import (
    CreateJobResponse,
)
from app.presentation.schemas.get_job_response import (
    GetJobResponse,
)
from app.presentation.schemas.list_events_response import (
    EventResponse,
    ListEventsResponse,
)
from app.presentation.schemas.list_jobs_response import (
    JobSummaryResponse,
    ListJobsResponse,
)

router = APIRouter(
    prefix="/jobs",
    tags=["Jobs"],
    dependencies=[
        Depends(require_api_key),
        Depends(require_rate_limit),
    ],
)


@router.post(
    "",
    response_model=CreateJobResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_job(
    request: CreateJobRequest,
    service: Annotated[
        CreateJobService,
        Depends(get_create_job_service),
    ],
) -> CreateJobResponse:
    """
    Create a new job.
    """
    resources = ResourceRequirements(
        cpu_cores=request.cpu_cores,
        memory_mib=request.memory_mib,
        vram_mib=request.vram_mib,
    )

    job = service.execute(
        resources,
        request.command,
    )

    return CreateJobResponse(
        id=str(job.id),
        status=job.status.name,
    )


@router.get(
    "",
    response_model=ListJobsResponse,
)
def list_jobs(
    service: Annotated[
        ListJobsService,
        Depends(get_list_jobs_service),
    ],
) -> ListJobsResponse:
    """
    Return the most recently submitted jobs.
    """
    jobs = service.execute()

    return ListJobsResponse(
        jobs=[
            JobSummaryResponse(
                id=str(job.id),
                status=job.status.name,
                cpu_cores=job.resources.cpu_cores,
                memory_mib=job.resources.memory_mib,
                vram_mib=job.resources.vram_mib,
                exit_code=job.exit_code,
                submitted_at=job.submitted_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
            )
            for job in jobs
        ]
    )


@router.get(
    "/queued",
    response_model=ListJobsResponse,
)
def list_queued_jobs(
    service: Annotated[
        ListQueuedJobsService,
        Depends(get_list_queued_jobs_service),
    ],
) -> ListJobsResponse:
    """
    Return every job currently sitting in the queue,
    waiting to be scheduled onto a node.
    """
    jobs = service.execute()

    return ListJobsResponse(
        jobs=[
            JobSummaryResponse(
                id=str(job.id),
                status=job.status.name,
                cpu_cores=job.resources.cpu_cores,
                memory_mib=job.resources.memory_mib,
                vram_mib=job.resources.vram_mib,
                exit_code=job.exit_code,
                submitted_at=job.submitted_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
            )
            for job in jobs
        ]
    )


@router.get(
    "/{job_id}",
    response_model=GetJobResponse,
    status_code=status.HTTP_200_OK,
)
def get_job(
    job_id: str,
    service: Annotated[
        GetJobService,
        Depends(get_get_job_service),
    ],
) -> GetJobResponse:
    """
    Retrieve an existing job.
    """
    try:
        job = service.execute(
            JobId(
                value=UUID(job_id),
            ),
        )
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return GetJobResponse(
        id=str(job.id),
        status=job.status.name,
        cpu_cores=job.resources.cpu_cores,
        memory_mib=job.resources.memory_mib,
        vram_mib=job.resources.vram_mib,
        exit_code=job.exit_code,
        submitted_at=job.submitted_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.get(
    "/{job_id}/history",
    response_model=ListEventsResponse,
    status_code=status.HTTP_200_OK,
)
def get_job_history(
    job_id: str,
    service: Annotated[
        GetJobHistoryService,
        Depends(get_get_job_history_service),
    ],
) -> ListEventsResponse:
    """
    Return every recorded event for a job, in the order
    they occurred.
    """

    events = service.execute(
        aggregate_id=job_id,
    )

    return ListEventsResponse(
        events=[
            EventResponse(
                id=str(event.id),
                aggregate_id=event.aggregate_id,
                aggregate_type=event.aggregate_type,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                payload=event.payload,
            )
            for event in events
        ]
    )


@router.post(
    "/{job_id}/cancel",
    response_model=GetJobResponse,
    status_code=status.HTTP_200_OK,
)
def cancel_job(
    job_id: str,
    service: Annotated[
        CancelJobService,
        Depends(get_cancel_job_service),
    ],
) -> GetJobResponse:
    """
    Cancel a job.

    Queued or scheduled jobs are cancelled immediately.
    A running job instead enters CANCELLING (ADR 0029): the
    request is recorded, but actual termination is delivered
    asynchronously to the worker on its next lease renewal,
    not by this endpoint. A job already CANCELLING is a
    no-op, returned unchanged rather than re-cancelled.

    A job that has already reached a terminal state cannot
    be cancelled -- that's a conflict with the job's current
    state, not a bad request or a missing resource.
    """
    job_uuid = JobId(
        value=UUID(job_id),
    )

    try:
        job = service.execute(job_uuid)
    except InvalidJobTransition as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found.",
        )

    return GetJobResponse(
        id=str(job.id),
        status=job.status.name,
        cpu_cores=job.resources.cpu_cores,
        memory_mib=job.resources.memory_mib,
        vram_mib=job.resources.vram_mib,
        exit_code=job.exit_code,
        submitted_at=job.submitted_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.post(
    "/{job_id}/retry",
    response_model=GetJobResponse,
    status_code=status.HTTP_200_OK,
)
def retry_job(
    job_id: str,
    service: Annotated[
        RetryJobService,
        Depends(get_retry_job_service),
    ],
) -> GetJobResponse:
    """
    Retry a failed job if it still has retries remaining.

    If the job isn't FAILED, or has exhausted its retry
    budget, it's returned unchanged rather than treated as
    an error -- asking to retry a job that doesn't need or
    can't accept a retry isn't a client mistake worth
    rejecting, it's a no-op worth reporting honestly.
    """
    job_uuid = JobId(
        value=UUID(job_id),
    )

    job = service.execute(job_uuid)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found.",
        )

    return GetJobResponse(
        id=str(job.id),
        status=job.status.name,
        cpu_cores=job.resources.cpu_cores,
        memory_mib=job.resources.memory_mib,
        vram_mib=job.resources.vram_mib,
        exit_code=job.exit_code,
        submitted_at=job.submitted_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )
