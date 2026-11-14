from __future__ import annotations

from app.domain.value_objects.job_id import JobId


class JobReclaimedError(Exception):
    """
    Raised when a job's outcome arrives after reconciliation
    reclaimed the job (ADR 0096 decision 10).

    The outcome is real but no longer canonical, the same as
    after a lost lease (ADR 0011), so it was not saved and the
    node was not credited. The reclaim already credited it.
    """

    def __init__(self, job_id: JobId) -> None:
        super().__init__(
            f"Job '{job_id}' was reclaimed before its outcome was "
            "saved. The outcome was not recorded."
        )
        self.job_id = job_id
