from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.domain.entities.job import Job
from app.domain.entities.node import Node
from app.domain.enums.worker_management import WorkerManagement
from app.domain.enums.worker_status import WorkerStatus
from app.domain.value_objects.worker_id import WorkerId


def utc_now() -> datetime:
    return datetime.now(UTC)


HEARTBEAT_TIMEOUT = timedelta(minutes=1)


@dataclass(slots=True)
class Worker:
    """
    Represents a worker process responsible for
    executing jobs on behalf of a compute node.
    """

    id: WorkerId
    node: Node

    status: WorkerStatus = WorkerStatus.STARTING
    managed_by: WorkerManagement = WorkerManagement.DASHBOARD

    running_job: Job | None = None

    last_seen_at: datetime = field(
        default_factory=utc_now,
    )

    def heartbeat(
        self,
    ) -> None:
        """
        Record that this worker is alive.
        """
        self.last_seen_at = utc_now()

    def is_alive(
        self,
    ) -> bool:
        """
        Return True if the worker has reported
        a heartbeat within the configured timeout.
        """
        return (
            utc_now() - self.last_seen_at
        ) <= HEARTBEAT_TIMEOUT

    def ready(
        self,
    ) -> None:
        """
        Transition the worker into the IDLE state.
        """
        self.status = WorkerStatus.IDLE

    def recover(
        self,
    ) -> None:
        """
        Recover this worker after abandoned work.

        Any running job is forgotten because the
        scheduler will decide what to do with it.
        """
        self.running_job = None
        self.status = WorkerStatus.IDLE

    def is_idle(
        self,
    ) -> bool:
        """
        Return True when the worker is available
        to execute a job.
        """
        return self.status is WorkerStatus.IDLE

    def is_offline(
        self,
    ) -> bool:
        """
        Return True when the worker is offline.
        """
        return self.status is WorkerStatus.OFFLINE

    def accept(
        self,
        job: Job,
    ) -> None:
        """
        Accept a scheduled job.
        """
        if not self.is_idle():
            raise ValueError(
                "Worker is not accepting jobs."
            )

        if job.assigned_node_id != self.node.id:
            raise ValueError(
                "Job is assigned to another node."
            )

        self.running_job = job
        self.status = WorkerStatus.BUSY

    def start(
        self,
    ) -> None:
        """
        Start the assigned job.
        """
        if self.running_job is None:
            raise ValueError(
                "No assigned job."
            )

        self.running_job.start()

    def complete(
        self,
        exit_code: int | None = None,
    ) -> None:
        """
        Complete the running job.
        """
        if self.running_job is None:
            raise ValueError(
                "No running job."
            )

        self.running_job.complete(
            exit_code=exit_code,
        )

        self.running_job = None
        self.status = WorkerStatus.IDLE

    def fail(
        self,
        exit_code: int | None = None,
    ) -> None:
        """
        Mark the running job as failed.
        """
        if self.running_job is None:
            raise ValueError(
                "No running job."
            )

        self.running_job.fail(
            exit_code=exit_code,
        )

        self.running_job = None
        self.status = WorkerStatus.IDLE

    def cancel_job(
        self,
        exit_code: int | None = None,
    ) -> None:
        """
        Confirm the running job's cancellation was actually
        applied to its subprocess (ADR 0029). Only legal
        while the job is in CANCELLING, the same guard
        Job.confirm_cancelled() already enforces.
        """
        if self.running_job is None:
            raise ValueError(
                "No running job."
            )

        self.running_job.confirm_cancelled(
            exit_code=exit_code,
        )

        self.running_job = None
        self.status = WorkerStatus.IDLE

    def drain(
        self,
    ) -> None:
        """
        Prevent the worker from accepting
        new work.
        """
        self.status = WorkerStatus.DRAINING

    def offline(
        self,
    ) -> None:
        """
        Transition the worker into the
        OFFLINE state.
        """
        self.status = WorkerStatus.OFFLINE
