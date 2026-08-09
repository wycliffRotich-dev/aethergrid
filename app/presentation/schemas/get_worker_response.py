from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RunningJobResponse(BaseModel):
    """
    The job currently assigned to a worker, including the
    fields an executing agent needs to actually run it.

    Deliberately separate from GetJobResponse and
    ListJobsResponse: command is scoped to this
    worker-facing endpoint only, per ADR 0020, never
    exposed through a public job-lookup endpoint.
    """

    id: str
    command: list[str] | None
    execution_timeout_seconds: float


class GetWorkerResponse(BaseModel):
    id: str
    status: str
    node_id: str
    last_seen_at: datetime
    running_job: RunningJobResponse | None
