from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities.api_key import ApiKey
from app.domain.value_objects.api_key_id import ApiKeyId
from app.domain.value_objects.tenant_id import TenantId


class ApiKeyRepository(ABC):
    """
    Repository contract for managing API keys.

    Implementations may store keys in memory, PostgreSQL, or
    any other persistence backend. There is deliberately no
    SQLite implementation of this contract: local development
    already runs against the same PostgreSQL backend
    production uses, so a SQLite ApiKeyRepository would
    reintroduce the environment drift that change eliminated.
    The `sqlite` storage backend falls back to the in-memory
    implementation for this repository, the same way it
    already does for Worker and Lease.

    Tenant rule (ADR 0064, point 4). Every method either takes
    a required TenantId, takes an entity that carries its own
    tenant_id, or has a name ending in _across_tenants. A
    lookup that omits the tenant cannot be written by
    accident, and one that spans tenants says so in its name.
    """

    @abstractmethod
    def save(
        self,
        api_key: ApiKey,
    ) -> None:
        """
        Persist an API key, creating it if it doesn't already
        exist or overwriting it in place if it does.

        The tenant travels inside the entity, and saving a key
        again never moves it to another tenant. This is the
        full-entity path: issuance and revocation both go
        through here, since neither is a hot-path operation.
        Recording that a key was just used goes through
        mark_used() instead, which skips loading the entity.

        Raises ApiKeyTenantConflictError when a key with this
        id already exists in another tenant. Nothing is
        written in that case.
        """
        raise NotImplementedError

    @abstractmethod
    def mark_used(
        self,
        api_key_id: ApiKeyId,
        tenant_id: TenantId,
    ) -> None:
        """
        Record that a key was just used, without requiring the
        caller to load and resave the whole entity first.

        Raises ApiKeyNotFoundError if no key with this id
        exists in this tenant. A key in another tenant is
        reported exactly like a missing one. Called on every
        authenticated request, so it must never fall back to
        creating a row: a call racing a revocation that
        deleted the row needs to fail, not resurrect a key
        that was just killed.
        """
        raise NotImplementedError

    @abstractmethod
    def get_by_id(
        self,
        api_key_id: ApiKeyId,
        tenant_id: TenantId,
    ) -> ApiKey | None:
        """
        Return the API key with this id in this tenant.

        Returns None when no such key exists in the tenant. A
        key that exists in another tenant also returns None,
        so a caller cannot tell the two cases apart (ADR 0064,
        point 5).
        """
        raise NotImplementedError

    @abstractmethod
    def get_by_hash_across_tenants(
        self,
        key_hash: str,
    ) -> ApiKey | None:
        """
        Return the API key matching this hash, in whichever
        tenant it belongs to.

        This is the one lookup that cannot take a tenant: the
        tenant is learned from the credential, never from the
        request (ADR 0064, point 3). Only authentication may
        call it. Looked up on every authenticated request, so
        it must be backed by an index. Returns None when no
        key matches.
        """
        raise NotImplementedError

    @abstractmethod
    def list_issued_by(
        self,
        issuer_id: ApiKeyId,
        tenant_id: TenantId,
    ) -> list[ApiKey]:
        """
        Return every API key in this tenant whose issued_by
        equals issuer_id (ADR 0056 follow-up), active or
        revoked alike.

        Revoked keys stay in the list deliberately: an owner
        reviewing what it issued should see its full history,
        not just what currently remains active.
        """
        raise NotImplementedError
