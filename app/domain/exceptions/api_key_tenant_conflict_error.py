from __future__ import annotations

from app.domain.exceptions.domain_error import DomainError


class ApiKeyTenantConflictError(DomainError):
    """
    Raised when saving an API key would touch a key that
    belongs to another tenant (ADR 0064).

    A save never moves a key between tenants and never changes
    another tenant's key. Key ids are generated, so reaching
    this means a bug in the caller, and it is reported instead
    of being ignored.
    """

    pass
