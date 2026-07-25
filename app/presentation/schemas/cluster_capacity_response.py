from pydantic import BaseModel


class ClusterCapacityResponse(BaseModel):
    """
    Response describing total available capacity
    across all alive nodes in the cluster.
    """

    cpu_cores: int
    memory_mib: int
    vram_mib: int
