from __future__ import annotations

from app.domain.exceptions.domain_error import DomainError


class JobStatusConflictError(DomainError):
    """
    Raised when concurrent writers repeatedly change a job's status
    before a fenced write can settle.
    """

    pass
