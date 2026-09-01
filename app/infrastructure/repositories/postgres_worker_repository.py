from __future__ import annotations

import json

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.enums.worker_management import WorkerManagement
from app.domain.enums.worker_status import WorkerStatus
from app.domain.repositories.worker_repository import WorkerRepository
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.worker_id import WorkerId


class PostgresWorkerRepository(WorkerRepository):
    """
    PostgreSQL-backed implementation of WorkerRepository.

    Uses raw psycopg (no ORM), consistent with
    PostgresNodeRepository and PostgresEventRepository.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def save(self, worker: Worker) -> None:
        running_job_id = (
            str(worker.running_job.id)
            if worker.running_job is not None
            else None
        )

        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO workers (
                    id, node_id, status, managed_by,
                    running_job_id, last_seen_at
                ) VALUES (
                    %(id)s, %(node_id)s, %(status)s, %(managed_by)s,
                    %(running_job_id)s, %(last_seen_at)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    node_id = EXCLUDED.node_id,
                    status = EXCLUDED.status,
                    managed_by = EXCLUDED.managed_by,
                    running_job_id = EXCLUDED.running_job_id,
                    last_seen_at = EXCLUDED.last_seen_at
                """,
                {
                    "id": str(worker.id),
                    "node_id": str(worker.node.id),
                    "status": worker.status.value,
                    "managed_by": worker.managed_by.value,
                    "running_job_id": running_job_id,
                    "last_seen_at": worker.last_seen_at,
                },
            )

    def get_by_id(self, worker_id: WorkerId) -> Worker | None:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                "SELECT * FROM workers WHERE id = %s",
                (str(worker_id),),
            ).fetchone()
        return self._to_entity(conn, row) if row else None

    def get_by_node_id(self, node_id: NodeId) -> Worker | None:
        """
        Retrieve the worker registered for a node, if one
        exists (ADR 0030).
        """
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                "SELECT * FROM workers WHERE node_id = %s",
                (str(node_id),),
            ).fetchone()
        return self._to_entity(conn, row) if row else None

    def list(self) -> list[Worker]:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            rows = conn.execute("SELECT * FROM workers").fetchall()
            return [self._to_entity(conn, row) for row in rows]

    def delete(self, worker_id: WorkerId) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "DELETE FROM workers WHERE id = %s",
                (str(worker_id),),
            )

    def _to_entity(self, conn, row: dict) -> Worker:
        """
        Reconstruct a Worker, including its Node.

        NOTE: this issues a second query per worker to
        fetch the owning Node. Acceptable for now given
        expected worker counts; worth revisiting with a
        JOIN if this repository ever needs to serve
        high-frequency list() calls at scale.
        """
        conn.row_factory = dict_row
        node_row = conn.execute(
            "SELECT * FROM nodes WHERE id = %s",
            (str(row["node_id"]),),
        ).fetchone()

        node = PostgresWorkerRepository._node_from_row(node_row)

        running_job_id = row["running_job_id"]
        running_job = None
        if running_job_id is not None:
            job_row = conn.execute(
                "SELECT * FROM jobs WHERE id = %s",
                (str(running_job_id),),
            ).fetchone()
            if job_row is not None:
                running_job = PostgresWorkerRepository._job_from_row(job_row)

        return Worker(
            id=WorkerId(row["id"]),
            node=node,
            status=WorkerStatus(row["status"]),
            managed_by=WorkerManagement(row["managed_by"]),
            running_job=running_job,
            last_seen_at=row["last_seen_at"],
        )

    @staticmethod
    def _node_from_row(row: dict) -> Node:
        from app.domain.value_objects.resource_requirements import (
            ResourceRequirements,
        )

        return Node(
            id=NodeId(row["id"]),
            capacity=ResourceRequirements(
                cpu_cores=row["capacity_cpu_cores"],
                memory_mib=row["capacity_memory_mib"],
                vram_mib=row["capacity_vram_mib"],
            ),
            available=ResourceRequirements(
                cpu_cores=row["available_cpu_cores"],
                memory_mib=row["available_memory_mib"],
                vram_mib=row["available_vram_mib"],
            ),
            labels=row["labels"] or {},
            last_seen_at=row["last_seen_at"],
            draining=row["draining"],
        )

    @staticmethod
    def _job_from_row(row: dict):

        from app.domain.entities.job import Job
        from app.domain.enums.job_status import JobStatus
        from app.domain.value_objects.resource_requirements import (
            ResourceRequirements,
        )

        assigned_node_id = (
            NodeId(row["assigned_node_id"])
            if row["assigned_node_id"] is not None
            else None
        )

        command = row["command"]
        if isinstance(command, str):
            command = json.loads(command)

        return Job(
            id=JobId(row["id"]),
            resources=ResourceRequirements(
                cpu_cores=row["cpu_cores"],
                memory_mib=row["memory_mib"],
                vram_mib=row["vram_mib"],
            ),
            priority=row["priority"],
            constraints=row["constraints"] or {},
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
