from __future__ import annotations

from app.domain.exceptions.domain_error import DomainError


class TenantAlreadyExistsError(DomainError):
    """
    Raised when saving a tenant would conflict with a different
    existing tenant: the name is held by another id, or the id
    already exists under another name (ADR 0064).
    """

    pass
