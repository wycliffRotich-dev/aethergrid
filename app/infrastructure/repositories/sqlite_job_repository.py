from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from uuid import UUID

from app.domain.entities.job import Job
from app.domain.enums.job_status import JobStatus
from app.domain.repositories.job_repository import (
    JobRepository,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    cpu_cores INTEGER NOT NULL,
    memory_mib INTEGER NOT NULL,
    vram_mib INTEGER NOT NULL,
    priority INTEGER NOT NULL,
    constraints TEXT NOT NULL,
    max_retries INTEGER NOT NULL,
    retry_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    assigned_node_id TEXT,
    submitted_at TEXT NOT NULL,
    command TEXT,
    exit_code INTEGER,
    cancellation_requested_at TEXT
);
"""


class SqliteJobRepository(JobRepository):
    """
    SQLite-backed implementation of the job repository.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        self._connection = connection
        self._connection.execute(_CREATE_TABLE_SQL)
        self._connection.commit()

    def save(
        self,
        job: Job,
    ) -> None:
        command = (
            json.dumps(job.command)
            if job.command is not None
            else None
        )

        self._connection.execute(
            """
            INSERT INTO jobs (
                id,
                cpu_cores,
                memory_mib,
                vram_mib,
                priority,
                constraints,
                max_retries,
                retry_count,
                status,
                assigned_node_id,
                submitted_at,
                command,
                exit_code,
                cancellation_requested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                cpu_cores = excluded.cpu_cores,
                memory_mib = excluded.memory_mib,
                vram_mib = excluded.vram_mib,
                priority = excluded.priority,
                constraints = excluded.constraints,
                max_retries = excluded.max_retries,
                retry_count = excluded.retry_count,
                status = excluded.status,
                assigned_node_id = excluded.assigned_node_id,
                submitted_at = excluded.submitted_at,
                command = excluded.command,
                exit_code = excluded.exit_code,
                cancellation_requested_at = excluded.cancellation_requested_at
            """,
            (
                str(job.id),
                job.resources.cpu_cores,
                job.resources.memory_mib,
                job.resources.vram_mib,
                job.priority,
                json.dumps(job.constraints),
                job.max_retries,
                job.retry_count,
                job.status.value,
                (str(job.assigned_node_id) if job.assigned_node_id is not None else None),
                job.submitted_at.isoformat(),
                command,
                job.exit_code,
                (
                    job.cancellation_requested_at.isoformat()
                    if job.cancellation_requested_at is not None
                    else None
                ),
            ),
        )
        self._connection.commit()

    def get_by_id(
        self,
        job_id: JobId,
    ) -> Job | None:
        row = self._connection.execute(
            "SELECT * FROM jobs WHERE id = ?",
            (str(job_id),),
        ).fetchone()

        if row is None:
            return None

        return self._row_to_job(row)

    def list(
        self,
    ) -> list[Job]:
        rows = self._connection.execute(
            "SELECT * FROM jobs",
        ).fetchall()

        return [self._row_to_job(row) for row in rows]

    def list_queued(
        self,
    ) -> list[Job]:
        """
        Return all queued jobs.
        """
        rows = self._connection.execute(
            "SELECT * FROM jobs WHERE status = ?",
            (JobStatus.QUEUED.value,),
        ).fetchall()

        return [self._row_to_job(row) for row in rows]

    def list_recent(
        self,
        limit: int,
    ) -> list[Job]:
        """
        Return the most recently submitted jobs, newest
        first, capped at `limit`. Ordering and the limit
        are both pushed down to SQLite via ORDER BY/LIMIT,
        rather than loading every row and slicing in Python.
        """
        rows = self._connection.execute(
            "SELECT * FROM jobs ORDER BY submitted_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

        return [self._row_to_job(row) for row in rows]

    def _row_to_job(
        self,
        row: sqlite3.Row,
    ) -> Job:
        assigned_node_id = (
            NodeId(value=UUID(row["assigned_node_id"]))
            if row["assigned_node_id"] is not None
            else None
        )

        command = (
            json.loads(row["command"])
            if row["command"] is not None
            else None
        )

        return Job(
            id=JobId(value=UUID(row["id"])),
            resources=ResourceRequirements(
                cpu_cores=row["cpu_cores"],
                memory_mib=row["memory_mib"],
                vram_mib=row["vram_mib"],
            ),
            priority=row["priority"],
            constraints=json.loads(row["constraints"]),
            max_retries=row["max_retries"],
            retry_count=row["retry_count"],
            status=JobStatus(row["status"]),
            assigned_node_id=assigned_node_id,
            submitted_at=datetime.fromisoformat(
                row["submitted_at"],
            ),
            command=command,
            exit_code=row["exit_code"],
            cancellation_requested_at=(
                datetime.fromisoformat(row["cancellation_requested_at"])
                if row["cancellation_requested_at"] is not None
                else None
            ),
        )
