from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class ApiKeyId:
    """
    Strongly typed identifier for an ApiKey.
    """

    value: UUID

    @classmethod
    def new(cls) -> ApiKeyId:
        """
        Create a new unique ApiKey identifier.
        """
        return cls(uuid4())

    def __str__(self) -> str:
        return str(self.value)
