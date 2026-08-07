from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.domain.entities.api_key import ApiKey
from app.domain.entities.lease import utc_now
from app.domain.exceptions.api_key_not_found_error import (
    ApiKeyNotFoundError,
)
from app.domain.repositories.api_key_repository import (
    ApiKeyRepository,
)
from app.domain.value_objects.api_key_id import ApiKeyId


class PostgresApiKeyRepository(ApiKeyRepository):
    """
    Uses raw psycopg (no ORM), consistent with
    PostgresLeaseRepository, PostgresNodeRepository, and
    PostgresWorkerRepository.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def save(self, api_key: ApiKey) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO api_keys (
                    id, key_hash, label, created_at,
                    revoked_at, last_used_at
                ) VALUES (
                    %(id)s, %(key_hash)s, %(label)s, %(created_at)s,
                    %(revoked_at)s, %(last_used_at)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    revoked_at = EXCLUDED.revoked_at,
                    last_used_at = EXCLUDED.last_used_at
                """,
                {
                    "id": str(api_key.id),
                    "key_hash": api_key.key_hash,
                    "label": api_key.label,
                    "created_at": api_key.created_at,
                    "revoked_at": api_key.revoked_at,
                    "last_used_at": api_key.last_used_at,
                },
            )

    def mark_used(self, api_key_id: ApiKeyId) -> None:
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
                """,
                {
                    "id": str(api_key_id),
                    "last_used_at": utc_now(),
                },
            )

            if cursor.rowcount == 0:
                raise ApiKeyNotFoundError(api_key_id)

    def get_by_id(self, api_key_id: ApiKeyId) -> ApiKey | None:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                "SELECT * FROM api_keys WHERE id = %s",
                (str(api_key_id),),
            ).fetchone()
        return self._to_entity(row) if row else None

    def get_by_hash(self, key_hash: str) -> ApiKey | None:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                "SELECT * FROM api_keys WHERE key_hash = %s",
                (key_hash,),
            ).fetchone()
        return self._to_entity(row) if row else None

    def list_active(self) -> list[ApiKey]:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(
                "SELECT * FROM api_keys WHERE revoked_at IS NULL"
            ).fetchall()
        return [self._to_entity(row) for row in rows]

    @staticmethod
    def _to_entity(row: dict) -> ApiKey:
        return ApiKey(
            id=ApiKeyId(row["id"]),
            key_hash=row["key_hash"],
            label=row["label"],
            created_at=row["created_at"],
            revoked_at=row["revoked_at"],
            last_used_at=row["last_used_at"],
        )
