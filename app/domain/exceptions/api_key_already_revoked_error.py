from __future__ import annotations

from app.domain.exceptions.domain_error import DomainError


class ApiKeyAlreadyRevokedError(DomainError):
    """
    Raised when attempting to revoke an API key that has
    already been revoked.
    """

    pass
