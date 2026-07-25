from pydantic import BaseModel


class WorkerSummaryResponse(BaseModel):
    """
    Summary view of a single worker.
    """

    id: str
    status: str
    node_id: str
    running_job_id: str | None


class ListWorkersResponse(BaseModel):
    """
    Response containing a list of registered workers.
    """

    workers: list[WorkerSummaryResponse]
