from __future__ import annotations

from app.domain.exceptions.domain_error import DomainError


class WorkerJobMismatchError(DomainError):
    """
    Raised when a caller attempts to start, complete, or fail
    a job on behalf of a worker that does not currently hold
    that exact job as its running_job.

    Shared across every endpoint that requires this ownership
    check (start, complete, fail), rather than one exception
    type per endpoint, since it is the same invariant being
    enforced in each case: this worker holds this job, right
    now, or it has no standing to report anything about it.
    """
