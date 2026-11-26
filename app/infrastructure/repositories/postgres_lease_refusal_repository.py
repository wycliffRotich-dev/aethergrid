from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.domain.entities.lease_refusal import LeaseRefusal
from app.domain.enums.lease_refusal_operation import LeaseRefusalOperation
from app.domain.enums.lease_refusal_reason import LeaseRefusalReason
from app.domain.repositories.lease_refusal_repository import (
    LeaseRefusalRepository,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId

_SELECT = """
    SELECT id, tenant_id, lease_id, worker_id, job_id,
           operation, reason, refused_at
    FROM lease_refusals
"""


class PostgresLeaseRefusalRepository(LeaseRefusalRepository):
    """
    PostgreSQL-backed implementation of LeaseRefusalRepository (ADR 0108).

    The table refuses a record whose reclaim record is missing or is in
    another tenant, and a record whose job is missing. A second record of
    the same kind for the same lease in the same tenant is no change, so
    the first one stays.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def save(self, refusal: LeaseRefusal) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO lease_refusals (
                    id, tenant_id, lease_id, worker_id, job_id,
                    operation, reason, refused_at
                ) VALUES (
                    %(id)s, %(tenant_id)s, %(lease_id)s, %(worker_id)s,
                    %(job_id)s, %(operation)s, %(reason)s, %(refused_at)s
                )
                ON CONFLICT (tenant_id, lease_id, operation, reason)
                DO NOTHING
                """,
                {
                    "id": str(refusal.id),
                    "tenant_id": str(refusal.tenant_id.value),
                    "lease_id": str(refusal.lease_id),
                    "worker_id": str(refusal.worker_id),
                    "job_id": str(refusal.job_id),
                    "operation": refusal.operation.value,
                    "reason": refusal.reason.value,
                    "refused_at": refusal.refused_at,
                },
            )

    def list_for_lease(
        self,
        lease_id: UUID,
        tenant_id: TenantId,
    ) -> list[LeaseRefusal]:
        with self._pool.connection() as conn:
            rows = conn.cursor(row_factory=dict_row).execute(
                _SELECT
                + " WHERE lease_id = %s AND tenant_id = %s"
                + " ORDER BY refused_at, id",
                (str(lease_id), str(tenant_id.value)),
            ).fetchall()

        return [self._to_entity(row) for row in rows]

    @staticmethod
    def _to_entity(row: dict[str, Any]) -> LeaseRefusal:
        return LeaseRefusal(
            id=row["id"],
            tenant_id=TenantId(row["tenant_id"]),
            lease_id=row["lease_id"],
            worker_id=WorkerId(row["worker_id"]),
            job_id=JobId(row["job_id"]),
            operation=LeaseRefusalOperation(row["operation"]),
            reason=LeaseRefusalReason(row["reason"]),
            refused_at=row["refused_at"],
        )
