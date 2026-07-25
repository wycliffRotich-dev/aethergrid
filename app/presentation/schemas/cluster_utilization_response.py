from pydantic import BaseModel


class ClusterUtilizationResponse(BaseModel):
    """
    Response describing total allocated (in-use)
    resources across all alive nodes in the cluster.
    """

    cpu_cores: int
    memory_mib: int
    vram_mib: int
