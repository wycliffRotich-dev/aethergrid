"""
The public, read-only application (ADR 0094).

A separate FastAPI app with its own route table. It serves GET routes from
an explicit allowlist, starts no loop, and does not import the private
routers or the composition root of the private API.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TypeVar

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.types import Lifespan

from app.application.public_rate_limiter import AnonymousRateLimiter
from app.application.public_read_port import PublicReadPort
from app.presentation.public.rate_limit_middleware import (
    AnonymousRateLimitMiddleware,
)
from app.presentation.public.responses import (
    PublicEventResponse,
    PublicJobResponse,
    PublicLeaseResponse,
    PublicNodeResponse,
    PublicWorkerResponse,
)
from app.presentation.public.settings import PublicSettings

logger = logging.getLogger(__name__)

# Each route reads this many rows. The reader cuts any limit to its own
# maximum, so this value is a request and not the guard (ADR 0102, decision 2).
ROW_LIMIT = 100
UNAVAILABLE_BODY = b'{"error":"unavailable"}'
# Reads that may run at once. The limiter bounds the rate of requests and
# not the number in flight, and each read holds a server thread while it
# waits. A read past this number is refused at once, so the health route
# and the rest of the server always have threads left. The value is a
# first choice and is not measured (ADR 0102).
MAX_READS_IN_FLIGHT = 20

_Model = TypeVar("_Model", bound=BaseModel)


def _unavailable() -> Response:
    return Response(
        content=UNAVAILABLE_BODY, status_code=503, media_type="application/json"
    )


def _respond(
    gate: threading.BoundedSemaphore, read: Callable[[], list[_Model]]
) -> list[_Model] | Response:
    # A failure of the read, or of the mapping of its rows, ends here, so the
    # body is fixed and carries nothing of the failure. The log keeps it.
    if not gate.acquire(blocking=False):
        return _unavailable()

    try:
        return read()
    except Exception:
        logger.exception("a read of the public app failed")
        return _unavailable()
    finally:
        gate.release()


def create_public_app(
    settings: PublicSettings,
    limiter: AnonymousRateLimiter | None = None,
    lifespan: Lifespan[FastAPI] | None = None,
    *,
    reader: PublicReadPort,
) -> FastAPI:
    app = FastAPI(
        title="AetherGrid public demo",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.allowed_origin],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=[],
    )

    # Added after CORS, so it is the outermost middleware and counts
    # every request, preflights included (ADR 0103, decision 7).
    app.add_middleware(
        AnonymousRateLimitMiddleware,
        limiter=limiter if limiter is not None else AnonymousRateLimiter(),
        trusted_proxy_hops=settings.trusted_proxy_hops,
        allowed_origin=settings.allowed_origin,
    )

    gate = threading.BoundedSemaphore(MAX_READS_IN_FLIGHT)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/public/nodes", response_model=list[PublicNodeResponse])
    def list_nodes() -> list[PublicNodeResponse] | Response:
        return _respond(
            gate,
            lambda: [
                PublicNodeResponse.from_record(row)
                for row in reader.list_nodes(ROW_LIMIT)
            ]
        )

    @app.get("/public/jobs", response_model=list[PublicJobResponse])
    def list_jobs() -> list[PublicJobResponse] | Response:
        return _respond(
            gate,
            lambda: [
                PublicJobResponse.from_record(row)
                for row in reader.list_jobs(ROW_LIMIT)
            ]
        )

    @app.get("/public/workers", response_model=list[PublicWorkerResponse])
    def list_workers() -> list[PublicWorkerResponse] | Response:
        return _respond(
            gate,
            lambda: [
                PublicWorkerResponse.from_record(row)
                for row in reader.list_workers(ROW_LIMIT)
            ]
        )

    @app.get("/public/leases", response_model=list[PublicLeaseResponse])
    def list_leases() -> list[PublicLeaseResponse] | Response:
        return _respond(
            gate,
            lambda: [
                PublicLeaseResponse.from_record(row)
                for row in reader.list_leases(ROW_LIMIT)
            ]
        )

    @app.get("/public/events", response_model=list[PublicEventResponse])
    def list_events() -> list[PublicEventResponse] | Response:
        return _respond(
            gate,
            lambda: [
                PublicEventResponse.from_record(row)
                for row in reader.list_events(ROW_LIMIT)
            ]
        )

    return app
