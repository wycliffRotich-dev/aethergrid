from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.domain.entities.job import DEFAULT_EXECUTION_TIMEOUT, Job
from app.domain.enums.job_status import JobStatus
from app.domain.exceptions.job_tenant_conflict_error import (
    JobTenantConflictError,
)
from app.domain.repositories.job_repository import JobRepository
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.tenant_id import TenantId


class PostgresJobRepository(JobRepository):
    """
    PostgreSQL-backed implementation of JobRepository.

    Uses raw psycopg (no ORM), consistent with
    PostgresNodeRepository, PostgresEventRepository, and
    PostgresWorkerRepository.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def save(self, job: Job) -> None:
        assigned_node_id = (
            str(job.assigned_node_id)
            if job.assigned_node_id is not None
            else None
        )

        command = (
            json.dumps(job.command)
            if job.command is not None
            else None
        )

        with self._pool.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO jobs (
                    id, cpu_cores, memory_mib, vram_mib,
                    priority, constraints, max_retries,
                    retry_count, status, assigned_node_id,
                    submitted_at, started_at, completed_at,
                    command, exit_code, cancellation_requested_at,
                    execution_timeout_seconds, tenant_id
                ) VALUES (
                    %(id)s, %(cpu_cores)s, %(memory_mib)s,
                    %(vram_mib)s, %(priority)s, %(constraints)s,
                    %(max_retries)s, %(retry_count)s, %(status)s,
                    %(assigned_node_id)s, %(submitted_at)s,
                    %(started_at)s, %(completed_at)s,
                    %(command)s, %(exit_code)s,
                    %(cancellation_requested_at)s,
                    %(execution_timeout_seconds)s,
                    %(tenant_id)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    cpu_cores = EXCLUDED.cpu_cores,
                    memory_mib = EXCLUDED.memory_mib,
                    vram_mib = EXCLUDED.vram_mib,
                    priority = EXCLUDED.priority,
                    constraints = EXCLUDED.constraints,
                    max_retries = EXCLUDED.max_retries,
                    retry_count = EXCLUDED.retry_count,
                    status = EXCLUDED.status,
                    assigned_node_id = EXCLUDED.assigned_node_id,
                    submitted_at = EXCLUDED.submitted_at,
                    started_at = EXCLUDED.started_at,
                    completed_at = EXCLUDED.completed_at,
                    command = EXCLUDED.command,
                    exit_code = EXCLUDED.exit_code,
                    cancellation_requested_at = EXCLUDED.cancellation_requested_at,
                    execution_timeout_seconds = EXCLUDED.execution_timeout_seconds
                WHERE jobs.tenant_id = EXCLUDED.tenant_id
                """,
                {
                    "id": str(job.id),
                    "cpu_cores": job.resources.cpu_cores,
                    "memory_mib": job.resources.memory_mib,
                    "vram_mib": job.resources.vram_mib,
                    "priority": job.priority,
                    "constraints": json.dumps(job.constraints),
                    "max_retries": job.max_retries,
                    "retry_count": job.retry_count,
                    "status": job.status.value,
                    "assigned_node_id": assigned_node_id,
                    "submitted_at": job.submitted_at,
                    "started_at": job.started_at,
                    "completed_at": job.completed_at,
                    "command": command,
                    "exit_code": job.exit_code,
                    "cancellation_requested_at": job.cancellation_requested_at,
                    "execution_timeout_seconds": (
                        job.execution_timeout.total_seconds()
                    ),
                    "tenant_id": str(job.tenant_id),
                },
            )

            if cursor.rowcount == 0:
                raise JobTenantConflictError(
                    f"job {job.id} belongs to another tenant"
                )

    def save_if_unchanged(
        self,
        job: Job,
        expected: Job,
    ) -> bool:
        if job.id != expected.id or job.tenant_id != expected.tenant_id:
            raise ValueError(
                "expected snapshot must share id and tenant_id with job"
            )

        assigned_node_id = (
            str(job.assigned_node_id)
            if job.assigned_node_id is not None
            else None
        )
        expected_assigned_node_id = (
            str(expected.assigned_node_id)
            if expected.assigned_node_id is not None
            else None
        )

        command = (
            json.dumps(job.command)
            if job.command is not None
            else None
        )

        with self._pool.connection() as conn:
            row = conn.cursor(row_factory=dict_row).execute(
                """
                WITH updated AS (
                    UPDATE jobs SET
                        cpu_cores = %(cpu_cores)s,
                        memory_mib = %(memory_mib)s,
                        vram_mib = %(vram_mib)s,
                        priority = %(priority)s,
                        constraints = %(constraints)s,
                        max_retries = %(max_retries)s,
                        retry_count = %(retry_count)s,
                        status = %(status)s,
                        assigned_node_id = %(assigned_node_id)s,
                        submitted_at = %(submitted_at)s,
                        started_at = %(started_at)s,
                        completed_at = %(completed_at)s,
                        command = %(command)s,
                        exit_code = %(exit_code)s,
                        cancellation_requested_at = %(cancellation_requested_at)s,
                        execution_timeout_seconds = %(execution_timeout_seconds)s
                    WHERE id = %(id)s
                      AND tenant_id = %(tenant_id)s
                      AND status = %(expected_status)s
                      AND retry_count = %(expected_retry_count)s
                      AND assigned_node_id IS NOT DISTINCT FROM %(expected_assigned_node_id)s
                      AND started_at IS NOT DISTINCT FROM %(expected_started_at)s
                      AND completed_at IS NOT DISTINCT FROM %(expected_completed_at)s
                      AND exit_code IS NOT DISTINCT FROM %(expected_exit_code)s
                      AND cancellation_requested_at IS NOT DISTINCT FROM
                          %(expected_cancellation_requested_at)s
                    RETURNING 1
                )
                SELECT
                    (SELECT tenant_id FROM jobs WHERE id = %(id)s) AS owner_tenant_id,
                    EXISTS (SELECT 1 FROM updated) AS did_update
                """,
                {
                    "id": str(job.id),
                    "cpu_cores": job.resources.cpu_cores,
                    "memory_mib": job.resources.memory_mib,
                    "vram_mib": job.resources.vram_mib,
                    "priority": job.priority,
                    "constraints": json.dumps(job.constraints),
                    "max_retries": job.max_retries,
                    "retry_count": job.retry_count,
                    "status": job.status.value,
                    "assigned_node_id": assigned_node_id,
                    "submitted_at": job.submitted_at,
                    "started_at": job.started_at,
                    "completed_at": job.completed_at,
                    "command": command,
                    "exit_code": job.exit_code,
                    "cancellation_requested_at": job.cancellation_requested_at,
                    "execution_timeout_seconds": (
                        job.execution_timeout.total_seconds()
                    ),
                    "tenant_id": str(job.tenant_id),
                    "expected_status": expected.status.value,
                    "expected_retry_count": expected.retry_count,
                    "expected_assigned_node_id": expected_assigned_node_id,
                    "expected_started_at": expected.started_at,
                    "expected_completed_at": expected.completed_at,
                    "expected_exit_code": expected.exit_code,
                    "expected_cancellation_requested_at": (
                        expected.cancellation_requested_at
                    ),
                },
            ).fetchone()

        assert row is not None

        if row["did_update"]:
            return True

        if (
            row["owner_tenant_id"] is not None
            and str(row["owner_tenant_id"]) != str(job.tenant_id)
        ):
            raise JobTenantConflictError(
                f"job {job.id} belongs to another tenant"
            )

        return False

    def get_by_id(
        self,
        job_id: JobId,
        tenant_id: TenantId,
    ) -> Job | None:
        with self._pool.connection() as conn:
            row = conn.cursor(row_factory=dict_row).execute(
                "SELECT * FROM jobs WHERE id = %s AND tenant_id = %s",
                (str(job_id), str(tenant_id)),
            ).fetchone()
        return self._to_entity(row) if row else None

    def list_queued(self, tenant_id: TenantId) -> list[Job]:
        with self._pool.connection() as conn:
            rows = conn.cursor(row_factory=dict_row).execute(
                "SELECT * FROM jobs WHERE status = %s AND tenant_id = %s",
                (JobStatus.QUEUED.value, str(tenant_id)),
            ).fetchall()
        return [self._to_entity(row) for row in rows]

    def list_recent(self, limit: int, tenant_id: TenantId) -> list[Job]:
        """
        Return the most recently submitted jobs in this tenant,
        newest first, capped at `limit`. Ordering and the limit
        are both pushed down to PostgreSQL via ORDER
        BY/LIMIT, rather than loading every row and slicing
        in Python.
        """
        with self._pool.connection() as conn:
            rows = conn.cursor(row_factory=dict_row).execute(
                "SELECT * FROM jobs WHERE tenant_id = %s "
                "ORDER BY submitted_at DESC LIMIT %s",
                (str(tenant_id), limit),
            ).fetchall()
        return [self._to_entity(row) for row in rows]

    def get_by_id_across_tenants(self, job_id: JobId) -> Job | None:
        with self._pool.connection() as conn:
            row = conn.cursor(row_factory=dict_row).execute(
                "SELECT * FROM jobs WHERE id = %s",
                (str(job_id),),
            ).fetchone()
        return self._to_entity(row) if row else None

    def list_across_tenants(self) -> list[Job]:
        with self._pool.connection() as conn:
            rows = (
                conn.cursor(row_factory=dict_row)
                .execute("SELECT * FROM jobs")
                .fetchall()
            )
        return [self._to_entity(row) for row in rows]

    @staticmethod
    def _to_entity(row: dict[str, Any]) -> Job:
        constraints = row["constraints"]
        if isinstance(constraints, str):
            constraints = json.loads(constraints)

        command = row["command"]
        if isinstance(command, str):
            command = json.loads(command)

        assigned_node_id = (
            NodeId(row["assigned_node_id"])
            if row["assigned_node_id"] is not None
            else None
        )

        return Job(
            id=JobId(row["id"]),
            tenant_id=TenantId(row["tenant_id"]),
            resources=ResourceRequirements(
                cpu_cores=row["cpu_cores"],
                memory_mib=row["memory_mib"],
                vram_mib=row["vram_mib"],
            ),
            priority=row["priority"],
            constraints=constraints or {},
            max_retries=row["max_retries"],
            retry_count=row["retry_count"],
            status=JobStatus(row["status"]),
            assigned_node_id=assigned_node_id,
            submitted_at=row["submitted_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            command=command,
            exit_code=row["exit_code"],
            cancellation_requested_at=row["cancellation_requested_at"],
            execution_timeout=(
                timedelta(seconds=row["execution_timeout_seconds"])
                if row["execution_timeout_seconds"] is not None
                else DEFAULT_EXECUTION_TIMEOUT
            ),
        )
