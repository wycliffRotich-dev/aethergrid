from __future__ import annotations

import json

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.domain.entities.job import Job
from app.domain.enums.job_status import JobStatus
from app.domain.repositories.job_repository import JobRepository
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)


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
            conn.execute(
                """
                INSERT INTO jobs (
                    id, cpu_cores, memory_mib, vram_mib,
                    priority, constraints, max_retries,
                    retry_count, status, assigned_node_id,
                    submitted_at, started_at, completed_at,
                    command, exit_code, cancellation_requested_at
                ) VALUES (
                    %(id)s, %(cpu_cores)s, %(memory_mib)s,
                    %(vram_mib)s, %(priority)s, %(constraints)s,
                    %(max_retries)s, %(retry_count)s, %(status)s,
                    %(assigned_node_id)s, %(submitted_at)s,
                    %(started_at)s, %(completed_at)s,
                    %(command)s, %(exit_code)s,
                    %(cancellation_requested_at)s
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
                    cancellation_requested_at = EXCLUDED.cancellation_requested_at
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
                },
            )

    def get_by_id(self, job_id: JobId) -> Job | None:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = %s",
                (str(job_id),),
            ).fetchone()
        return self._to_entity(row) if row else None

    def list(self) -> list[Job]:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute("SELECT * FROM jobs").fetchall()
        return [self._to_entity(row) for row in rows]

    def list_queued(self) -> list[Job]:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = %s",
                (JobStatus.QUEUED.value,),
            ).fetchall()
        return [self._to_entity(row) for row in rows]

    def list_recent(self, limit: int) -> list[Job]:
        """
        Return the most recently submitted jobs, newest
        first, capped at `limit`. Ordering and the limit
        are both pushed down to PostgreSQL via ORDER
        BY/LIMIT, rather than loading every row and slicing
        in Python.
        """
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY submitted_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [self._to_entity(row) for row in rows]

    @staticmethod
    def _to_entity(row: dict) -> Job:
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
        )
