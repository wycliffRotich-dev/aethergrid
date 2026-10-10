from __future__ import annotations

from app.domain.exceptions.domain_error import DomainError


class JobTenantConflictError(DomainError):
    """
    Raised when saving a job would touch a job that belongs to
    another tenant (ADR 0064).

    A save never moves a job between tenants and never changes
    another tenant's job. Job ids are generated, so reaching this
    means a bug in the caller, and it is reported instead of being
    ignored.
    """

    pass
