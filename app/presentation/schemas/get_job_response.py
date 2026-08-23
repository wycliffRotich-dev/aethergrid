from datetime import datetime

from pydantic import BaseModel


class GetJobResponse(BaseModel):
    """
    Response returned when retrieving a job.

    Deliberately excludes `command`. As of ADR 0028,
    command IS settable through the public API, but reading
    it back through this response would let any caller
    browsing jobs by ID inspect a command they didn't
    necessarily set. ADR 0020 scoped command *reads* to only
    the worker currently assigned that exact job, via
    GET /workers/{worker_id}. This schema intentionally
    does not widen that.
    """

    id: str
    status: str
    cpu_cores: int
    memory_mib: int
    vram_mib: int
    exit_code: int | None
    submitted_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
