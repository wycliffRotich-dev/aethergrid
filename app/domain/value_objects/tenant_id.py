from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class TenantId:
    """
    Strongly typed identifier for a tenant (ADR 0064).
    """

    value: UUID

    def __init__(
        self,
        value: str | UUID,
    ) -> None:
        object.__setattr__(
            self,
            "value",
            UUID(str(value)),
        )

    @classmethod
    def new(cls) -> TenantId:
        return cls(uuid4())

    @classmethod
    def from_string(
        cls,
        value: str,
    ) -> TenantId:
        return cls(UUID(value))

    def __str__(self) -> str:
        return str(self.value)
