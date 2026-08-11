from enum import StrEnum


class WorkerManagement(StrEnum):
    """
    Represents how a worker's job execution is managed:
    either driven by the in-process cluster tick loop
    (DASHBOARD, the historical default), or by a standalone
    agent process polling and executing over HTTP (AGENT,
    see ADR 0019). ClusterTickService uses this to decide
    which workers it's still responsible for executing jobs
    on behalf of.
    """

    DASHBOARD = "DASHBOARD"
    AGENT = "AGENT"
