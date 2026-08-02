from datetime import datetime

from pydantic import BaseModel


class WorkerSummaryResponse(BaseModel):
    """
    Summary view of a single worker.
    """

    id: str
    status: str
    node_id: str
    running_job_id: str | None
    last_seen_at: datetime


class ListWorkersResponse(BaseModel):
    """
    Response containing a list of registered workers.
    """

    workers: list[WorkerSummaryResponse]
