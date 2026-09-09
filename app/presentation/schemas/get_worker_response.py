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

    lease_id (ADR 0036) is the identity of the lease this
    worker currently holds for this job, read directly from
    the poll response an agent already receives before it
    ever starts executing. The agent must echo this back
    when reporting an outcome, so the server can fence the
    report against the lease that was actually current when
    execution began, not just whatever lease happens to be
    current at report time (ADR 0034's own deferred gap: a
    stale agent reporting against a since-reassigned lease
    for the same worker and job would otherwise pass every
    existing check).
    """

    id: str
    status: str
    command: list[str] | None
    execution_timeout_seconds: float
    lease_id: str | None


class GetWorkerResponse(BaseModel):
    id: str
    status: str
    node_id: str
    last_seen_at: datetime
    running_job: RunningJobResponse | None
