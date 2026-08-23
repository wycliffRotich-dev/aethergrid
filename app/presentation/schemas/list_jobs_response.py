from datetime import datetime

from pydantic import BaseModel


class JobSummaryResponse(BaseModel):
    """
    A single job as shown in a job listing.

    Deliberately excludes `command`, same reasoning as
    GetJobResponse: settable since ADR 0028, but reads stay
    scoped to the assigned worker per ADR 0020. This schema
    only ever reflects execution outcome (status,
    exit_code), never the command that produced it.
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


class ListJobsResponse(BaseModel):
    """
    HTTP response returned when listing jobs.
    """

    jobs: list[JobSummaryResponse]
