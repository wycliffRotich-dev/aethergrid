from pydantic import BaseModel


class NodeResponse(BaseModel):
    """
    Representation of a compute node.
    """

    id: str
    cpu_cores: int
    memory_mib: int
    vram_mib: int
    available_cpu_cores: int
    available_memory_mib: int
    available_vram_mib: int
    is_alive: bool
    is_draining: bool


class ListNodesResponse(BaseModel):
    """
    Response returned when listing
    registered compute nodes.
    """

    nodes: list[NodeResponse]
