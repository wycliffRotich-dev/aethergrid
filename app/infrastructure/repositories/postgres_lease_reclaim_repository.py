from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.domain.entities.lease_reclaim import LeaseReclaim
from app.domain.enums.lease_recovery_path import LeaseRecoveryPath
from app.domain.repositories.lease_reclaim_repository import (
    LeaseReclaimRepository,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId

_SELECT = """
    SELECT id, tenant_id, lease_id, worker_id, job_id,
           lease_acquired_at, lease_expires_at, reclaimed_at, recovered_by
    FROM lease_reclaims
"""


class PostgresLeaseReclaimRepository(LeaseReclaimRepository):
    """
    PostgreSQL-backed implementation of LeaseReclaimRepository (ADR 0107).

    The table refuses a record whose job is missing or is in another
    tenant, and a second record for the same lease in the same tenant.
    save() lets the first refusal raise as the driver reports it, and
    turns the second into no change.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def save(self, record: LeaseReclaim) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO lease_reclaims (
                    id, tenant_id, lease_id, worker_id, job_id,
                    lease_acquired_at, lease_expires_at, reclaimed_at,
                    recovered_by
                ) VALUES (
                    %(id)s, %(tenant_id)s, %(lease_id)s, %(worker_id)s,
                    %(job_id)s, %(lease_acquired_at)s, %(lease_expires_at)s,
                    %(reclaimed_at)s, %(recovered_by)s
                )
                ON CONFLICT (tenant_id, lease_id) DO NOTHING
                """,
                {
                    "id": str(record.id),
                    "tenant_id": str(record.tenant_id.value),
                    "lease_id": str(record.lease_id),
                    "worker_id": str(record.worker_id),
                    "job_id": str(record.job_id),
                    "lease_acquired_at": record.lease_acquired_at,
                    "lease_expires_at": record.lease_expires_at,
                    "reclaimed_at": record.reclaimed_at,
                    "recovered_by": record.recovered_by.value,
                },
            )

    def get_by_lease_id(
        self,
        lease_id: UUID,
        tenant_id: TenantId,
    ) -> LeaseReclaim | None:
        with self._pool.connection() as conn:
            row = conn.cursor(row_factory=dict_row).execute(
                _SELECT + " WHERE lease_id = %s AND tenant_id = %s",
                (str(lease_id), str(tenant_id.value)),
            ).fetchone()

        return self._to_entity(row) if row else None

    @staticmethod
    def _to_entity(row: dict[str, Any]) -> LeaseReclaim:
        return LeaseReclaim(
            id=row["id"],
            tenant_id=TenantId(row["tenant_id"]),
            lease_id=row["lease_id"],
            worker_id=WorkerId(row["worker_id"]),
            job_id=JobId(row["job_id"]),
            lease_acquired_at=row["lease_acquired_at"],
            lease_expires_at=row["lease_expires_at"],
            reclaimed_at=row["reclaimed_at"],
            recovered_by=LeaseRecoveryPath(row["recovered_by"]),
        )
