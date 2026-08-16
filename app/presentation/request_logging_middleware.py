from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.application.services.request_logging_service import (
    RequestLoggingService,
)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs every request's outcome via RequestLoggingService (see
    ADR 0022).

    Built as ASGI middleware, not a FastAPI dependency, since a
    dependency's teardown code cannot reliably observe the true
    response status code on the success path -- FastAPI has not
    yet populated it at the point a dependency's teardown runs.
    Middleware runs after the real response is built and reads
    its actual status_code directly. This was confirmed
    empirically before this class was written, not assumed.

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
    ) -> None:
        super().__init__(app)
        self._service = service or RequestLoggingService()

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.monotonic()

        response = await call_next(request)

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
