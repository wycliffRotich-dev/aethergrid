from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class ReportJobOutcomeRequest(BaseModel):
    """
    Shared request body for complete, fail, and cancel: the
    real exit code an agent observed. A terminated process's
    exit code (typically the negated signal number on Linux)
    is just as real an observation for a cancellation as it
    is for a normal completion or failure (ADR 0029).

    lease_id (ADR 0036) is the identity of the lease the
    caller believed it held when it started executing this
    job, echoed back from RunningJobResponse.lease_id. It is
    required, not optional: without it, the service has no
    way to distinguish a genuinely current report from a
    stale one reporting against a lease that was reclaimed
    and reassigned to someone else in the meantime, closing
    the gap ADR 0034 named and deferred for this exact,
    external HTTP path.
    """

    exit_code: int | None = None
    lease_id: UUID
