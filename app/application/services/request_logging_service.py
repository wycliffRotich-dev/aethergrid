from __future__ import annotations

import logging

_DENIAL_STATUS_CODES = frozenset({401, 429})


class RequestLoggingService:
    """
    Emits one structured log record per completed HTTP request
    (see ADR 0022).

    Framework-agnostic: accepts already-extracted primitive
    fields rather than a FastAPI Request/Response object, so
    this service carries no FastAPI import, consistent with
    every other application service in this codebase. Log
    formatting itself (JSON output) is configured once at
    startup in app/presentation/api.py; this service only
    decides which fields exist on a request log record and at
    what level each outcome is logged.

    Never accepts, and never logs, the raw Authorization header
    or raw API key in any form -- only a caller_id already
    resolved by the caller of this service (see ADR 0022's
    explicit rejection of logging credentials).
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
    ) -> None:
        self._logger = logger or logging.getLogger(
            "aethergrid.requests"
        )

    def log_completed_request(
        self,
        *,
        method: str,
        path: str,
        caller_id: str | None,
        status_code: int,
        duration_ms: float,
    ) -> None:
        """
        Log a request that reached a final status code.

        Covers both handler outcomes (200s, and handler-raised
        HTTPExceptions such as 404 or 409) and authentication
        or rate-limit denials (401, 429) when the caller of
        this service is require_api_key or require_rate_limit
        directly, rather than the log_request dependency (see
        ADR 0022: log_request only runs once authentication has
        already succeeded, so it cannot itself observe a 401).

        caller_id is None for a request that never resolved an
        authenticated identity, i.e. a 401 raised by
        require_api_key before any ApiKey was established.
        """
        level = (
            logging.WARNING
            if status_code in _DENIAL_STATUS_CODES
            else logging.INFO
        )

        self._logger.log(
            level,
            "request completed",
            extra={
                "method": method,
                "path": path,
                "caller_id": caller_id,
                "status_code": status_code,
                "duration_ms": duration_ms,
            },
        )
