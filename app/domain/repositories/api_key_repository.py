from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities.api_key import ApiKey
from app.domain.value_objects.api_key_id import ApiKeyId


class ApiKeyRepository(ABC):
    """
    Repository contract for managing API keys.

    Implementations may store keys in memory, PostgreSQL, or
    any other persistence backend. There is deliberately no
    SQLite implementation of this contract -- local
    development already runs against the same PostgreSQL
    backend production uses (see the Docker Compose
    consolidation), so a SQLite ApiKeyRepository would
    reintroduce the exact environment drift that change
    eliminated. The `sqlite` storage backend falls back to
    the in-memory implementation for this repository, the
    same way it already does for Worker and Lease.
    """

    @abstractmethod
    def save(
        self,
        api_key: ApiKey,
    ) -> None:
        """
        Persist an API key, creating it if it doesn't already
        exist or overwriting it in place if it does.

        This is the full-entity path -- issuance and
        revocation both go through here, since neither is a
        hot-path operation. Recording that a key was just
        used should go through mark_used() instead, which
        skips loading the entity entirely.
        """
        raise NotImplementedError

    @abstractmethod
    def mark_used(
        self,
        api_key_id: ApiKeyId,
    ) -> None:
        """
        Record that a key was just used, without requiring the
        caller to load and resave the whole entity first.

        Raises ApiKeyNotFoundError if no key with this id
        currently exists. Called on every authenticated
        request, so it must never fall back to creating a row
        -- a call racing a revocation that deleted the row out
        from under it needs to fail, not resurrect a key that
        was just killed.
        """
        raise NotImplementedError

    @abstractmethod
    def get_by_id(
        self,
        api_key_id: ApiKeyId,
    ) -> ApiKey | None:
        """
        Return the API key with this id.

        Returns None when no key with this id exists.
        """
        raise NotImplementedError

    @abstractmethod
    def get_by_hash(
        self,
        key_hash: str,
    ) -> ApiKey | None:
        """
        Return the API key matching this hash.

        Looked up on every authenticated request; must be
        backed by an index. Returns None when no key matches.
        """
        raise NotImplementedError

    @abstractmethod
    def list_active(
        self,
    ) -> list[ApiKey]:
        """
        Return every API key that has not been revoked.
        """
        raise NotImplementedError
