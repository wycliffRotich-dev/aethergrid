from __future__ import annotations

from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.domain.entities.tenant import Tenant
from app.domain.exceptions.tenant_already_exists_error import (
    TenantAlreadyExistsError,
)
from app.domain.repositories.tenant_repository import (
    TenantRepository,
)
from app.domain.value_objects.tenant_id import TenantId


class PostgresTenantRepository(TenantRepository):
    """
    Uses raw psycopg (no ORM), consistent with the other
    Postgres repositories.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def save(
        self,
        tenant: Tenant,
    ) -> None:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO tenants (id, name, created_at)
                    VALUES (%(id)s, %(name)s, %(created_at)s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    {
                        "id": str(tenant.id),
                        "name": tenant.name,
                        "created_at": tenant.created_at,
                    },
                )
            except UniqueViolation as exc:
                raise TenantAlreadyExistsError(
                    f"tenant name '{tenant.name}' is already "
                    "held by a different tenant"
                ) from exc

            if cursor.rowcount == 1:
                return

            # The id already exists. That is only acceptable when
            # it is the same tenant being saved again.
            existing = conn.execute(
                "SELECT name FROM tenants WHERE id = %s",
                (str(tenant.id),),
            ).fetchone()

        if existing is None:
            raise RuntimeError(
                f"tenant {tenant.id} disappeared while saving"
            )

        if existing["name"] != tenant.name:
            raise TenantAlreadyExistsError(
                f"tenant {tenant.id} already exists under a "
                "different name"
            )

    def get_by_id(
        self,
        tenant_id: TenantId,
    ) -> Tenant | None:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                "SELECT * FROM tenants WHERE id = %s",
                (str(tenant_id),),
            ).fetchone()
        return None if row is None else self._to_entity(row)

    def get_by_name(
        self,
        name: str,
    ) -> Tenant | None:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                "SELECT * FROM tenants WHERE name = %s",
                (name,),
            ).fetchone()
        return None if row is None else self._to_entity(row)

    @staticmethod
    def _to_entity(row: dict) -> Tenant:
        return Tenant(
            id=TenantId(row["id"]),
            name=row["name"],
            created_at=row["created_at"],
        )
