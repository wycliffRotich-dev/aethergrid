from pydantic import BaseModel


class CreateNodeRequest(BaseModel):
    """
    Request for registering a compute node.
    """

    cpu_cores: int
    memory_mib: int
    vram_mib: int
    name: str | None = None
