from __future__ import annotations

from app.domain.value_objects.worker_id import WorkerId


class NoActiveLeaseError(Exception):
    """
    Raised when a caller expects a worker to currently hold
    an active lease and it does not, either because the
    worker never acquired one, or because reconciliation
    already reclaimed it.

    Distinct from LeaseNotFoundError, which is raised when a
    specific lease id that was already looked up no longer
    exists at the moment of a follow-up operation (a race
    with reconciliation mid-renewal). This exception is
    raised earlier, when the initial lookup by worker_id
    itself comes back empty.
    """

    def __init__(self, worker_id: WorkerId) -> None:
        super().__init__(
            f"Worker '{worker_id}' does not own an active lease."
        )
        self.worker_id = worker_id
