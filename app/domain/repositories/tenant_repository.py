from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities.tenant import Tenant
from app.domain.value_objects.tenant_id import TenantId


class TenantRepository(ABC):
    """
    Repository contract for tenants (ADR 0064).

    A tenant is the isolation boundary itself, not a record owned
    by one, so unlike the repositories for tenant-owned resources
    its methods take no tenant argument. The test that inspects
    repository signatures for ADR 0064 must name this exemption.

    The default tenant exists in every implementation from the
    start: schema.sql inserts it and the in-memory implementation
    seeds it. There is no SQLite implementation, so the sqlite
    storage backend falls back to the in-memory one, the same way
    it already does for API keys.
    """

    @abstractmethod
    def save(
        self,
        tenant: Tenant,
    ) -> None:
        """
        Create a tenant. Saving a tenant that already exists
        unchanged is a no-op, so a bootstrap script can be run
        again. A tenant is immutable, so saving an id that exists
        under a different name, or a name already held by a
        different id, raises TenantAlreadyExistsError and changes
        nothing.
        """
        ...

    @abstractmethod
    def get_by_id(
        self,
        tenant_id: TenantId,
    ) -> Tenant | None: ...

    @abstractmethod
    def get_by_name(
        self,
        name: str,
    ) -> Tenant | None:
        """
        Exact, case-sensitive match on the stored name.
        """
        ...
