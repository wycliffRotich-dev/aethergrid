from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.domain.enums.job_status import JobStatus
from app.domain.exceptions.invalid_job_transition import (
    InvalidJobTransition,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


DEFAULT_EXECUTION_TIMEOUT = timedelta(
    hours=1,
)


@dataclass(slots=True)
class Job:
    """
    Represents a schedulable job in the system.
    """

    id: JobId
    resources: ResourceRequirements

    priority: int = 0

    constraints: dict[str, str] = field(
        default_factory=dict,
    )

    max_retries: int = 0

    retry_count: int = 0

    execution_timeout: timedelta = (
        DEFAULT_EXECUTION_TIMEOUT
    )

    status: JobStatus = JobStatus.SUBMITTED

    assigned_node_id: NodeId | None = None

    submitted_at: datetime = field(
        default_factory=utc_now,
    )

    started_at: datetime | None = None

    completed_at: datetime | None = None

    cancellation_requested_at: datetime | None = None
    """
    When cancellation was requested for a RUNNING job (ADR
    0029). None unless request_cancellation() has been
    called. Distinct from completed_at: a job can sit in
    CANCELLING, cancellation requested but not yet confirmed,
    for a real bounded window while the signal is delivered
    on the worker's next lease renewal.
    """

    command: list[str] | None = None
    """
    The argv-style command this job executes, e.g.
    ["python", "train.py", "--epochs", "5"].

    Deliberately a list, never a raw shell string, so a
    worker never needs shell=True and this can never be
    used for shell injection.

    None by default. Settable through the public API as of
    ADR 0028: any authenticated caller may set an arbitrary
    command when creating a job. This is a deliberate,
    scoped decision, not an oversight, see ADR 0028 for the
    blast-radius reasoning and the condition under which it
    must be revisited.
    """

    exit_code: int | None = None
    """
    The process exit code from the most recent execution
    attempt. None until the job has actually run once.
    """

    _ALLOWED_TRANSITIONS = {
        JobStatus.SUBMITTED: {
            JobStatus.QUEUED,
        },
        JobStatus.QUEUED: {
            JobStatus.SCHEDULED,
            JobStatus.CANCELLED,
        },
        JobStatus.SCHEDULED: {
            JobStatus.RUNNING,
            JobStatus.CANCELLED,
            JobStatus.QUEUED,
            JobStatus.FAILED,
        },
        JobStatus.RUNNING: {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.QUEUED,
            JobStatus.CANCELLING,
        },
        JobStatus.CANCELLING: {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.COMPLETED: set(),
        JobStatus.FAILED: {
            JobStatus.QUEUED,
        },
        JobStatus.CANCELLED: set(),
    }

    def __post_init__(
        self,
    ) -> None:
        """
        Validate that this job requests a meaningful
        amount of work.
        """
        if self.resources.cpu_cores <= 0:
            raise ValueError(
                "Job must request at least one CPU core."
            )

        if self.resources.memory_mib <= 0:
            raise ValueError(
                "Job must request a positive amount of memory."
            )

    def _transition_to(
        self,
        new_status: JobStatus,
    ) -> None:
        allowed = self._ALLOWED_TRANSITIONS[
            self.status
        ]

        if new_status not in allowed:
            raise InvalidJobTransition(
                f"Cannot transition from {self.status.name} to {new_status.name}."
            )

        self.status = new_status

    #
    # Queries
    #

    def is_submitted(
        self,
    ) -> bool:
        return self.status is JobStatus.SUBMITTED

    def is_queued(
        self,
    ) -> bool:
        return self.status is JobStatus.QUEUED

    def is_scheduled(
        self,
    ) -> bool:
        return self.status is JobStatus.SCHEDULED

    def is_running(
        self,
    ) -> bool:
        return self.status is JobStatus.RUNNING

    def is_completed(
        self,
    ) -> bool:
        return self.status is JobStatus.COMPLETED

    def is_failed(
        self,
    ) -> bool:
        return self.status is JobStatus.FAILED

    def is_cancelled(
        self,
    ) -> bool:
        return self.status is JobStatus.CANCELLED

    def is_cancelling(
        self,
    ) -> bool:
        return self.status is JobStatus.CANCELLING

    def has_timed_out(
        self,
    ) -> bool:
        """
        Return True when a running job has exceeded
        its execution timeout.
        """
        if self.started_at is None:
            return False

        return (
            utc_now() - self.started_at
        ) >= self.execution_timeout

    #
    # Commands
    #

    def queue(
        self,
    ) -> None:
        self._transition_to(
            JobStatus.QUEUED,
        )

    def assign_to(
        self,
        node_id: NodeId,
    ) -> None:
        self.assigned_node_id = node_id

        self._transition_to(
            JobStatus.SCHEDULED,
        )

    def unschedule(
        self,
    ) -> None:
        """
        Return a scheduled job to the queue.
        """
        if not self.is_scheduled():
            raise InvalidJobTransition(
                "Only scheduled jobs may be unscheduled."
            )

        self.assigned_node_id = None

        self._transition_to(
            JobStatus.QUEUED,
        )

    def start(
        self,
    ) -> None:
        self.started_at = utc_now()

        self._transition_to(
            JobStatus.RUNNING,
        )

    def complete(
        self,
        exit_code: int | None = None,
    ) -> None:
        self.completed_at = utc_now()
        self.exit_code = exit_code

        self._transition_to(
            JobStatus.COMPLETED,
        )

    def fail(
        self,
        exit_code: int | None = None,
    ) -> None:
        self.completed_at = utc_now()
        self.exit_code = exit_code

        self._transition_to(
            JobStatus.FAILED,
        )

    def cancel(
        self,
    ) -> None:
        self._transition_to(
            JobStatus.CANCELLED,
        )

    def request_cancellation(
        self,
    ) -> None:
        """
        Request cancellation of a job that is already
        RUNNING (ADR 0029).

        This does not stop anything by itself. It makes the
        request visible by moving the job to CANCELLING;
        actually terminating the subprocess happens
        asynchronously, delivered on the worker's next lease
        renewal. A job in CANCELLING may still legitimately
        resolve to COMPLETED or FAILED if it finishes before
        that signal is delivered -- whichever actually
        happens first wins, the same way a lease renewal that
        loses a race against reconciliation drops its result
        rather than overwrite the real outcome.
        """
        self.cancellation_requested_at = utc_now()

        self._transition_to(
            JobStatus.CANCELLING,
        )

    def confirm_cancelled(
        self,
        exit_code: int | None = None,
    ) -> None:
        """
        Confirm that a job's subprocess was actually
        terminated after a cancellation request (ADR 0029).

        Only legal from CANCELLING: a job that was never
        asked to cancel has nothing to confirm.
        """
        self.completed_at = utc_now()
        self.exit_code = exit_code

        self._transition_to(
            JobStatus.CANCELLED,
        )

    def can_retry(
        self,
    ) -> bool:
        """
        Return True if the job has retries remaining.
        """
        return self.retry_count < self.max_retries

    def record_retry(
        self,
    ) -> None:
        """
        Consume one retry attempt.
        """
        if not self.can_retry():
            raise ValueError(
                "Job has exhausted all retries."
            )

        self.retry_count += 1

    def retry(
        self,
    ) -> None:
        """
        Retry a failed job.
        """
        if not self.is_failed():
            raise InvalidJobTransition(
                "Only failed jobs may be retried."
            )

        self.record_retry()

        self.assigned_node_id = None

        self.started_at = None
        self.completed_at = None
        self.exit_code = None
        self.cancellation_requested_at = None

        self._transition_to(
            JobStatus.QUEUED,
        )

    def reclaim(
        self,
    ) -> None:
        """
        Reclaim a job abandoned due to infrastructure failure
        (a dead worker, an offline node, or an expired lease),
        as opposed to a job that failed on its own merits.

        Legal while the job is SCHEDULED, RUNNING, or
        CANCELLING, since those are the only states in which a
        worker could plausibly still be holding it.

        A CANCELLING job is finalized as CANCELLED instead of
        retried (ADR 0031): cancellation was already requested
        before the worker died, so the dead worker didn't
        prevent that outcome, it just failed to confirm it.
        Retrying would start a fresh execution attempt the
        caller never asked for and had already asked to stop.
        No retry attempt is consumed for this path, since
        retry accounting exists to bound attempts to run a
        job, not attempts to stop one.

        Reclaiming a SCHEDULED or RUNNING job consumes a retry
        attempt, using the same accounting as retry(). This is
        deliberate: without it, a single unhealthy node could
        cause a job to be endlessly reassigned and
        re-abandoned, consuming scheduling cycles and node
        capacity indefinitely without ever reaching a terminal
        state. Once retries are exhausted, the job fails
        instead of requeuing again.
        """
        if self.is_cancelling():
            self.assigned_node_id = None
            self.completed_at = utc_now()

            self._transition_to(
                JobStatus.CANCELLED,
            )
            return

        if not (
            self.is_scheduled() or self.is_running()
        ):
            raise InvalidJobTransition(
                "Only scheduled, running, or cancelling jobs "
                "may be reclaimed."
            )

        if not self.can_retry():
            self.assigned_node_id = None
            self.completed_at = utc_now()

            self._transition_to(
                JobStatus.FAILED,
            )
            return

        self.record_retry()

        self.assigned_node_id = None

        self.started_at = None
        self.completed_at = None
        self.exit_code = None

        self._transition_to(
            JobStatus.QUEUED,
        )
