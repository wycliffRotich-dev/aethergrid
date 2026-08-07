from __future__ import annotations

from app.domain.exceptions.domain_error import DomainError


class ApiKeyNotFoundError(DomainError):
    """
    Raised when no API key exists for the given identifier.
    """

    pass
