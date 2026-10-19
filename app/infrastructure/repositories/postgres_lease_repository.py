from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.domain.entities.lease import Lease, utc_now
from app.domain.exceptions.lease_not_found_error import LeaseNotFoundError
from app.domain.exceptions.worker_not_found_error import WorkerNotFoundError
from app.domain.repositories.lease_repository import (
    LeaseRepository,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId

# The keys that tie a lease to its worker. A lease for a worker that is
# gone, or that is in another tenant than the lease, violates one of
# them. Migration 0005 drops the first, so both are named (ADR 0075).
_WORKER_KEYS = frozenset(
    {
        "leases_worker_id_fkey",
        "leases_worker_same_tenant",
    }
)

# A lease an older image wrote between migrations 0004 and 0005 has no
# tenant, and neither may its worker. It then belongs to the tenant of
# its worker's node, which is never null (ADR 0075).
_SELECT = """
    SELECT l.id, l.worker_id, l.job_id, l.acquired_at, l.expires_at,
           COALESCE(l.tenant_id, w.tenant_id, n.tenant_id) AS tenant_id
    FROM leases l
    JOIN workers w ON w.id = l.worker_id
    JOIN nodes n ON n.id = w.node_id
"""


class PostgresLeaseRepository(LeaseRepository):
    """
    Uses raw psycopg (no ORM), consistent with
    PostgresNodeRepository, PostgresEventRepository, and
    PostgresWorkerRepository.

    Assumes the referenced worker and job already exist in
    storage; the leases table enforces this via foreign key
    constraints on worker_id and job_id. This mirrors the
    production call path (AssignWorkerService ->
    AcquireLeaseService), where both are always persisted
    before a lease is acquired.

    That assumption can still be invalidated by a concurrent
    write: a node can go offline and be removed (cascading
    the delete to its workers) in the narrow window between
    AssignWorkerService reading the worker as IDLE and this
    save() actually running. save() surfaces that race as a
    typed WorkerNotFoundError instead of letting the raw FK
    violation propagate, so callers can treat it the same way
    they already treat "no worker was available".
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def save(self, lease: Lease) -> None:
        try:
            with self._pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO leases (
                        id, worker_id, job_id, tenant_id,
                        acquired_at, expires_at
                    ) VALUES (
                        %(id)s, %(worker_id)s, %(job_id)s,
                        %(tenant_id)s, %(acquired_at)s, %(expires_at)s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        worker_id = EXCLUDED.worker_id,
                        job_id = EXCLUDED.job_id,
                        tenant_id = EXCLUDED.tenant_id,
                        acquired_at = EXCLUDED.acquired_at,
                        expires_at = EXCLUDED.expires_at
                    """,
                    {
                        "id": str(lease.id),
                        "worker_id": str(lease.worker_id),
                        "job_id": str(lease.job_id),
                        "tenant_id": str(lease.tenant_id.value),
                        "acquired_at": lease.acquired_at,
                        "expires_at": lease.expires_at,
                    },
                )
        except psycopg.errors.ForeignKeyViolation as exc:
            if exc.diag.constraint_name in _WORKER_KEYS:
                raise WorkerNotFoundError(lease.worker_id) from exc
            raise

    def renew(self, lease_id: UUID, duration: timedelta) -> None:
        # deliberately a plain UPDATE, not an upsert -- if the row's
        # gone (reconciliation reclaimed it while we were mid-renewal),
        # rowcount comes back 0 and we raise instead of recreatingit
        with self._pool.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE leases
                SET expires_at = %(expires_at)s
                WHERE id = %(id)s
                """,
                {
                    "id": str(lease_id),
                    "expires_at": utc_now() + duration,
                },
            )

            if cursor.rowcount == 0:
                raise LeaseNotFoundError(lease_id)

    def get_by_job_id(self, job_id: JobId) -> Lease | None:
        with self._pool.connection() as conn:
            row = conn.cursor(row_factory=dict_row).execute(
                _SELECT + " WHERE l.job_id = %s",
                (str(job_id),),
            ).fetchone()
        return self._to_entity(row) if row else None

    def get_by_worker_id(self, worker_id: WorkerId) -> Lease | None:
        with self._pool.connection() as conn:
            row = conn.cursor(row_factory=dict_row).execute(
                _SELECT + " WHERE l.worker_id = %s",
                (str(worker_id),),
            ).fetchone()
        return self._to_entity(row) if row else None

    def list(self) -> list[Lease]:
        with self._pool.connection() as conn:
            rows = (
                conn.cursor(row_factory=dict_row)
                .execute(_SELECT)
                .fetchall()
            )
        return [self._to_entity(row) for row in rows]

    def delete(self, job_id: JobId) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "DELETE FROM leases WHERE job_id = %s",
                (str(job_id),),
            )

    def delete_if_expired(self, job_id: JobId) -> bool:
        with self._pool.connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM leases
                WHERE job_id = %(job_id)s
                AND expires_at < %(now)s
                """,
                {
                    "job_id": str(job_id),
                    "now": utc_now(),
                },
            )
            return cursor.rowcount > 0

    @staticmethod
    def _to_entity(row: dict) -> Lease:
        return Lease(
            id=row["id"],
            worker_id=WorkerId(row["worker_id"]),
            job_id=JobId(row["job_id"]),
            tenant_id=TenantId(row["tenant_id"]),
            acquired_at=row["acquired_at"],
            expires_at=row["expires_at"],
        )
