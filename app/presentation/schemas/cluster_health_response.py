from pydantic import BaseModel


class ClusterHealthResponse(BaseModel):
    """
    Response describing the health of the cluster.
    """

    total_nodes: int
    alive_nodes: int
    offline_nodes: int
