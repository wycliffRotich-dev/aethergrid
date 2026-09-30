from __future__ import annotations

from collections.abc import Collection

from app.domain.exceptions.scope_denied_error import (
    ScopeDeniedError,
)
from app.domain.value_objects.api_key_scope import JOBS_EXECUTE


def authorize_job_creation(
    scopes: Collection[str],
    command: list[str] | None,
) -> None:
    """
    Decide whether a caller holding scopes may create a job
    with command (ADR 0054).

    A job with no command needs no scope, exactly as before.
    Any command at all needs jobs:execute. The test is
    `is None`, not truthiness, so an empty command list is
    still treated as setting a command and cannot slip past
    the gate.

    Pure policy: no I/O, no request or framework types.
    """
    if command is None:
        return

    if JOBS_EXECUTE not in scopes:
        raise ScopeDeniedError(JOBS_EXECUTE)
