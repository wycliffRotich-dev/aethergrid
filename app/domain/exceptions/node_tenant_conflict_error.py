from __future__ import annotations

from app.domain.exceptions.domain_error import DomainError


class NodeTenantConflictError(DomainError):
    """
    Raised when saving a node would touch a node that belongs
    to another tenant (ADR 0064).

    A save never moves a node between tenants and never changes
    another tenant's node. Node ids are generated, so reaching
    this means a bug in the caller, and it is reported instead
    of being ignored.
    """

    pass
