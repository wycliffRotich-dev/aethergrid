from __future__ import annotations

from collections.abc import Iterable

from app.domain.exceptions.domain_error import DomainError


class UnknownApiKeyScopeError(DomainError):
    """
    Raised when an API key is issued with a scope outside the
    closed scope vocabulary (ADR 0054).
    """

    def __init__(self, scope: str, known: Iterable[str]) -> None:
        self.scope = scope
        super().__init__(
            f"unknown API key scope {scope!r}; "
            f"known scopes: {', '.join(sorted(known))}"
        )
