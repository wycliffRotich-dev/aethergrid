from __future__ import annotations

from app.domain.entities.tenant import (
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_NAME,
    Tenant,
)
from app.domain.exceptions.tenant_already_exists_error import (
    TenantAlreadyExistsError,
)
from app.domain.repositories.tenant_repository import (
    TenantRepository,
)
from app.domain.value_objects.tenant_id import TenantId


class InMemoryTenantRepository(TenantRepository):
    """
    In-memory implementation of the TenantRepository.

    Starts with the default tenant, matching what schema.sql
    gives a Postgres database, so both backends begin in the same
    state.
    """

    def __init__(self) -> None:
        default = Tenant(
            id=DEFAULT_TENANT_ID,
            name=DEFAULT_TENANT_NAME,
        )
        self._tenants: dict[str, Tenant] = {
            str(default.id): default,
        }

    def save(
        self,
        tenant: Tenant,
    ) -> None:
        existing = self._tenants.get(str(tenant.id))

        if existing is not None:
            if existing.name != tenant.name:
                raise TenantAlreadyExistsError(
                    f"tenant {tenant.id} already exists under a "
                    "different name"
                )
            return

        for other in self._tenants.values():
            if other.name == tenant.name:
                raise TenantAlreadyExistsError(
                    f"tenant name '{tenant.name}' is already "
                    "held by a different tenant"
                )

        self._tenants[str(tenant.id)] = tenant

    def get_by_id(
        self,
        tenant_id: TenantId,
    ) -> Tenant | None:
        return self._tenants.get(str(tenant_id))

    def get_by_name(
        self,
        name: str,
    ) -> Tenant | None:
        for tenant in self._tenants.values():
            if tenant.name == name:
                return tenant
        return None
