from __future__ import annotations

from app.domain.exceptions.domain_error import DomainError


class ScopeDeniedError(DomainError):
    """
    Raised when an authenticated caller attempts an operation
    that requires a scope its API key does not hold (ADR 0054).
    """

    def __init__(self, scope: str) -> None:
        self.scope = scope
        super().__init__(
            f"this operation requires the {scope!r} scope"
        )
