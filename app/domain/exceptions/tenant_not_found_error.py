from __future__ import annotations

from app.domain.exceptions.domain_error import DomainError


class TenantNotFoundError(DomainError):
    """
    Raised when an operation names a tenant that does not exist
    (ADR 0064).
    """

    pass
