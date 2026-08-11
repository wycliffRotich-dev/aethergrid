from pydantic import BaseModel


class CreateWorkerRequest(BaseModel):
    """
    Request payload for registering a worker.

    managed_by defaults to "DASHBOARD" for backward compatibility
    with existing callers (the dashboard's RegisterNodeForm). Only
    scripts/run_agent.py sends "AGENT" explicitly, marking the
    resulting worker as owned by a standalone agent process rather
    than ClusterTickService's in-process execution loop (ADR 0019,
    issue #90).
    """

    node_id: str
    managed_by: str = "DASHBOARD"