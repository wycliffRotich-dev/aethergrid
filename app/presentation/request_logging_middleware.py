from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.application.services.error_tracking_service import (
    ErrorTrackingService,
)
from app.application.services.request_logging_service import (
    RequestLoggingService,
)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs every request's outcome via RequestLoggingService (see
    ADR 0022), and captures unhandled exceptions via
    ErrorTrackingService (see ADR 0023).

    Built as ASGI middleware, not a FastAPI dependency, since a
    dependency's teardown code cannot reliably observe the true
    response status code on the success path -- FastAPI has not
    yet populated it at the point a dependency's teardown runs.
    Middleware runs after the real response is built and reads
    its actual status_code directly. This was confirmed
    empirically before this class was written, not assumed.

    call_next is wrapped in try/except: without it, an
    unhandled exception from a route handler would skip
    logging and error capture entirely, since dispatch would
    exit before reaching either call (also confirmed
    empirically, see ADR 0023's context). On exception, the
    request is logged as a 500 and the error is captured,
    then the original exception is re-raised untouched so the
    response Starlette actually sends is unaffected.

    Reads request.state.caller_id, set by require_api_key as a
    side effect once it authenticates a caller (see
    app/presentation/auth.py), rather than re-parsing the
    Authorization header itself. Defaults to None when
    authentication never succeeded on this request, e.g. a 401.
    """

    def __init__(
        self,
        app: ASGIApp,
        service: RequestLoggingService | None = None,
        error_tracking_service: ErrorTrackingService | None = None,
    ) -> None:
        super().__init__(app)
        self._service = service or RequestLoggingService()
        self._error_tracking_service = (
            error_tracking_service or ErrorTrackingService()
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.monotonic()

        try:
            response = await call_next(request)
        except Exception as exc:
            # caller_id is only ever set by the route handler
            # itself (via require_api_key), which runs inside
            # call_next -- it must be read here, after call_next
            # has run (even though it raised), never before.
            caller_id = getattr(request.state, "caller_id", None)
            # An unhandled exception here means Starlette will
            # send a 500, but without this except block the
            # request would otherwise be invisible to this
            # codebase's own logging entirely -- neither logged
            # nor captured (see ADR 0023: this gap was found by
            # testing this exact path before it was fixed).
            duration_ms = (time.monotonic() - start) * 1000

            self._error_tracking_service.capture_error(
                source="request",
                exc=exc,
                context={
                    "method": request.method,
                    "path": request.url.path,
                    "caller_id": caller_id,
                },
            )

            self._service.log_completed_request(
                method=request.method,
                path=request.url.path,
                caller_id=caller_id,
                status_code=500,
                duration_ms=duration_ms,
            )

            raise

        duration_ms = (time.monotonic() - start) * 1000
        caller_id = getattr(request.state, "caller_id", None)

        self._service.log_completed_request(
            method=request.method,
            path=request.url.path,
            caller_id=caller_id,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        return response
