from __future__ import annotations

from dataclasses import dataclass

from app.domain.entities.tenant import Tenant
from app.domain.exceptions.tenant_not_found_error import (
    TenantNotFoundError,
)
from app.domain.repositories.tenant_repository import (
    TenantRepository,
)


@dataclass(frozen=True, slots=True)
class ResolvedTenant:
    """
    The tenant a name resolved to, and whether this call created it.

    created lets a caller say what happened without a second
    lookup, which would be racy and would need repository access.
    """

    tenant: Tenant
    created: bool


class ResolveTenantService:
    """
    Returns the tenant with a given name (ADR 0090).

    The name is trimmed and matched exactly, with case. When no
    tenant has the name, one is created only if create_if_missing
    is true, and TenantNotFoundError is raised otherwise, so a
    mistyped name cannot open a new isolation boundary.

    If another operator creates the same name between the lookup
    and the save, the repository raises TenantAlreadyExistsError
    and nothing changes. That error is not caught here.
    """

    def __init__(self, tenants: TenantRepository) -> None:
        self._tenants = tenants

    def execute(
        self,
        name: str,
        *,
        create_if_missing: bool = False,
    ) -> ResolvedTenant:
        name = name.strip()
        if not name:
            raise ValueError(
                "tenant name must be a non-empty, "
                "human-readable identifier"
            )

        existing = self._tenants.get_by_name(name)
        if existing is not None:
            return ResolvedTenant(tenant=existing, created=False)

        if not create_if_missing:
            raise TenantNotFoundError(f"tenant '{name}' does not exist")

        tenant = Tenant.create(name)
        self._tenants.save(tenant)
        return ResolvedTenant(tenant=tenant, created=True)
