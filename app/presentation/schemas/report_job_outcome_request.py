from __future__ import annotations

from pydantic import BaseModel


class ReportJobOutcomeRequest(BaseModel):
    """
    Shared request body for both complete and fail: the real
    exit code an agent observed, if the job actually ran a
    command. Jobs created through the public API currently
    have no command (ADR 0012), so this is None in practice
    today, but the shape matches what a real command's exit
    code will be once ADR 0020's agent execution path is
    connected to job creation.
    """

    exit_code: int | None = None
