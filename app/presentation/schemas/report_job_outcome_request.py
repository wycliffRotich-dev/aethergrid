from __future__ import annotations

from pydantic import BaseModel


class ReportJobOutcomeRequest(BaseModel):
    """
    Shared request body for complete, fail, and cancel: the
    real exit code an agent observed. A terminated process's
    exit code (typically the negated signal number on Linux)
    is just as real an observation for a cancellation as it
    is for a normal completion or failure (ADR 0029).
    """

    exit_code: int | None = None
