from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.domain.entities.api_key import ApiKey
from app.domain.entities.lease import utc_now
from app.domain.exceptions.api_key_not_found_error import (
    ApiKeyNotFoundError,
)
from app.domain.exceptions.api_key_tenant_conflict_error import (
    ApiKeyTenantConflictError,
)
from app.domain.repositories.api_key_repository import (
    ApiKeyRepository,
)
from app.domain.value_objects.api_key_id import ApiKeyId
from app.domain.value_objects.tenant_id import TenantId


class PostgresApiKeyRepository(ApiKeyRepository):
    """
    Uses raw psycopg (no ORM), consistent with
    PostgresLeaseRepository, PostgresNodeRepository, and
    PostgresWorkerRepository.

    Every tenant-scoped query carries the tenant in its own
    WHERE clause, so a key in another tenant is
    indistinguishable from a missing one (ADR 0064, point 5).
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def save(self, api_key: ApiKey) -> None:
        # The update branch never writes tenant_id, and it only
        # fires when the existing row is in the same tenant, so
        # a save can neither move a key between tenants nor
        # modify another tenant's row. When the guard blocks
        # the update, no row is affected and the save is
        # reported as a conflict.
        with self._pool.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO api_keys (
                    id, key_hash, label, created_at,
                    revoked_at, last_used_at, scopes, issued_by,
                    tenant_id
                ) VALUES (
                    %(id)s, %(key_hash)s, %(label)s, %(created_at)s,
                    %(revoked_at)s, %(last_used_at)s, %(scopes)s,
                    %(issued_by)s, %(tenant_id)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    revoked_at = EXCLUDED.revoked_at,
                    last_used_at = EXCLUDED.last_used_at,
                    scopes = EXCLUDED.scopes
                WHERE api_keys.tenant_id = EXCLUDED.tenant_id
                """,
                {
                    "id": str(api_key.id),
                    "key_hash": api_key.key_hash,
                    "label": api_key.label,
                    "created_at": api_key.created_at,
                    "revoked_at": api_key.revoked_at,
                    "last_used_at": api_key.last_used_at,
                    "scopes": list(api_key.scopes),
                    "tenant_id": str(api_key.tenant_id),
                    "issued_by": (
                        str(api_key.issued_by)
                        if api_key.issued_by is not None
                        else None
                    ),
                },
            )

            if cursor.rowcount == 0:
                raise ApiKeyTenantConflictError(
                    f"api key {api_key.id} belongs to another tenant"
                )

    def mark_used(
        self,
        api_key_id: ApiKeyId,
        tenant_id: TenantId,
    ) -> None:
        # deliberately a plain UPDATE, not an upsert -- if the
        # row's gone (revoked and deleted out from under us),
        # rowcount comes back 0 and we raise instead of
        # recreating it, same reasoning as
        # PostgresLeaseRepository.renew()
        with self._pool.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE api_keys
                SET last_used_at = %(last_used_at)s
                WHERE id = %(id)s
                  AND tenant_id = %(tenant_id)s
                """,
                {
                    "id": str(api_key_id),
                    "tenant_id": str(tenant_id),
                    "last_used_at": utc_now(),
                },
            )

            if cursor.rowcount == 0:
                raise ApiKeyNotFoundError(api_key_id)

    def get_by_id(
        self,
        api_key_id: ApiKeyId,
        tenant_id: TenantId,
    ) -> ApiKey | None:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                """
                SELECT * FROM api_keys
                WHERE id = %s AND tenant_id = %s
                """,
                (str(api_key_id), str(tenant_id)),
            ).fetchone()
        return self._to_entity(row) if row else None

    def get_by_hash_across_tenants(
        self,
        key_hash: str,
    ) -> ApiKey | None:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                "SELECT * FROM api_keys WHERE key_hash = %s",
                (key_hash,),
            ).fetchone()
        return self._to_entity(row) if row else None

    def list_issued_by(
        self,
        issuer_id: ApiKeyId,
        tenant_id: TenantId,
    ) -> list[ApiKey]:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(
                """
                SELECT * FROM api_keys
                WHERE issued_by = %s AND tenant_id = %s
                """,
                (str(issuer_id), str(tenant_id)),
            ).fetchall()
        return [self._to_entity(row) for row in rows]

    @staticmethod
    def _to_entity(row: dict) -> ApiKey:
        return ApiKey(
            id=ApiKeyId(row["id"]),
            key_hash=row["key_hash"],
            label=row["label"],
            created_at=row["created_at"],
            tenant_id=TenantId(row["tenant_id"]),
            revoked_at=row["revoked_at"],
            last_used_at=row["last_used_at"],
            scopes=frozenset(row.get("scopes") or []),
            issued_by=(
                ApiKeyId(row["issued_by"])
                if row.get("issued_by") is not None
                else None
            ),
        )
