from __future__ import annotations

import logging
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class CapturedError:
    """
    A single structured error record (see ADR 0023).
    """

    occurred_at: datetime
    source: str
    exception_type: str
    exception_message: str
    traceback: str
    context: dict[str, object] = field(default_factory=dict)


class ErrorTrackingService:
    """
    Captures unhandled exceptions as structured records (see
    ADR 0023).

    Framework-agnostic: takes an already-caught exception and a
    caller-supplied source label, no FastAPI import, consistent
    with every other application service in this codebase.

    Logs via the standard logging module, at ERROR with
    exc_info, so captured errors flow through the same JSON
    formatter configured in app/presentation/api.py (see ADR
    0022), and keeps a bounded in-memory record of the most
    recent errors: a live, queryable view a log stream alone
    does not give. No external service, no alerting; both are
    explicitly deferred by ADR 0023.

    An internal failure (e.g. deque append raising for some
    reason) is swallowed rather than propagated, so error
    tracking can never itself mask or interrupt the exception,
    or the response, that triggered it.
    """

    def __init__(
        self,
        max_stored_errors: int = 200,
        logger: logging.Logger | None = None,
    ) -> None:
        if max_stored_errors <= 0:
            raise ValueError(
                "max_stored_errors must be a positive number."
            )

        self._errors: deque[CapturedError] = deque(
            maxlen=max_stored_errors
        )
        self._logger = logger or logging.getLogger(
            "aethergrid.errors"
        )

    def capture_error(
        self,
        *,
        source: str,
        exc: Exception,
        context: dict[str, object] | None = None,
    ) -> None:
        """
        Capture an already-caught exception.

        source identifies where this came from, e.g. "request",
        "cluster_tick", "reconciliation" (see ADR 0023). context
        carries whatever fields are relevant to that source.

        Never raises: a failure inside error tracking itself
        must not mask or replace the original exception the
        caller is already handling.
        """
        try:
            self._logger.error(
                "unhandled error captured",
                exc_info=exc,
                extra={
                    "source": source,
                    "exception_type": type(exc).__name__,
                },
            )

            record = CapturedError(
                occurred_at=datetime.now(UTC),
                source=source,
                exception_type=type(exc).__name__,
                exception_message=str(exc),
                traceback="".join(
                    traceback.format_exception(
                        type(exc), exc, exc.__traceback__
                    )
                ),
                context=context or {},
            )

            self._errors.append(record)
        except Exception:
            pass

    def recent_errors(self) -> list[CapturedError]:
        """
        Return the most recently captured errors, oldest first,
        up to the configured maximum.
        """
        return list(self._errors)
