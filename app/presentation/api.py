from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from psycopg_pool import ConnectionPool

from app.presentation.dependencies import (
    get_cluster_tick_service,
    get_connection_pool,
    get_reconciliation_loop,
    get_request_logging_service,
)
from app.presentation.request_logging_middleware import (
    RequestLoggingMiddleware,
)
from app.presentation.routers.api_keys import (
    router as api_keys_router,
)
from app.presentation.routers.cluster import (
    router as cluster_router,
)
from app.presentation.routers.events import (
    router as events_router,
)
from app.presentation.routers.jobs import (
    router as jobs_router,
)
from app.presentation.routers.nodes import (
    router as nodes_router,
)
from app.presentation.routers.workers import (
    router as workers_router,
)

logger = logging.getLogger(__name__)

TICK_INTERVAL_SECONDS = 1.0


class _JsonFormatter(logging.Formatter):
    """
    Renders every log record as a single JSON line (see
    ADR 0022). Configured once, at startup, on the root
    logger, so this applies uniformly to request logs
    (RequestLoggingService, "aethergrid.requests") and the
    existing cluster-loop logs (this module's own logger)
    alike, without either needing its own configuration.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for field in (
            "method",
            "path",
            "caller_id",
            "status_code",
            "duration_ms",
        ):
            if hasattr(record, field):
                payload[field] = getattr(record, field)

        if record.exc_info:
            payload["exc_info"] = self.formatException(
                record.exc_info
            )

        return json.dumps(payload)


def _configure_logging() -> None:
    """
    Configure the root logger once, at startup, with a JSON
    formatter (see ADR 0022). Configuring the root logger,
    rather than a single named logger, means every logger in
    this application, present and future, is covered without
    needing individual setup.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

    # Configuring the root logger at INFO applies to every
    # logger in the process, not only this application's own.
    # httpx, used internally by TestClient in this codebase's
    # own test suite (and by anything else using httpx as an
    # HTTP client), logs its own request line at INFO; left
    # unconstrained, that log line would now propagate to our
    # handler too, indistinguishable from this application's
    # own request logs. Held at WARNING here so this stays
    # scoped to what ADR 0022 actually asked for: uniform
    # coverage of this application's logging, not every
    # dependency's internal logging as a side effect.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


_configure_logging()


async def _run_cluster_tick(
    cluster_tick_service,
    reconciliation_loop,
) -> None:
    """
    Run one cluster tick: a scheduling/execution pass
    followed by one reconciliation pass.

    Each phase is isolated in its own try/except so a
    failure in one can't prevent the other from running
    this tick, or prevent the next tick from running at
    all. Extracted from _run_cluster_loop so this failure
    isolation is directly testable without a while-loop
    or a sleep.
    """
    try:
        await asyncio.to_thread(
            cluster_tick_service.execute,
        )
    except Exception:
        logger.exception(
            "Unexpected error running cluster tick.",
        )

    try:
        reconciliation_loop.execute()
    except Exception:
        logger.exception(
            "Unexpected error running reconciliation.",
        )


async def _run_cluster_loop() -> None:
    """
    Repeatedly drive the cluster forward: schedule queued
    jobs, assign idle workers, and execute assigned work,
    then reconcile any state left inconsistent by dead
    workers, expired leases, or offline nodes.

    Runs as a background asyncio task for the lifetime of
    the application. See _run_cluster_tick for the
    per-phase failure isolation this loop relies on.

    ClusterTickService.execute() now runs on a worker thread via
    asyncio.to_thread (ADR 0032), since it may execute a
    job's real, arbitrary command (ADR 0028) for an
    unbounded, caller-controlled duration. Without this, a
    single long-running job would block this event loop,
    and with it every other request this server handles, for
    the job's entire execution.

    ReconciliationLoop.execute() is deliberately left as a
    direct call, not threaded: it never executes a job's
    command, and its work (marking dead workers, reclaiming
    expired leases, recovering offline nodes) is bounded and
    repository-bound, so moving it would add thread-hop
    overhead with no corresponding benefit (ADR 0032).
    """
    cluster_tick_service = get_cluster_tick_service()
    reconciliation_loop = get_reconciliation_loop()

    while True:
        await _run_cluster_tick(
            cluster_tick_service,
            reconciliation_loop,
        )

        await asyncio.sleep(TICK_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_run_cluster_loop())

    yield

    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="NeuroMesh API",
    description="Distributed AI Control Plane",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "https://aethergrid-dashboard.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    RequestLoggingMiddleware,
    service=get_request_logging_service(),
)

app.include_router(
    cluster_router,
)
app.include_router(
    jobs_router,
)
app.include_router(
    nodes_router,
)
app.include_router(
    workers_router,
)
app.include_router(
    events_router,
)
app.include_router(
    api_keys_router,
)

@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Welcome to NeuroMesh API",
    }


HEALTH_CHECK_TIMEOUT_SECONDS = 2.0


@app.get("/health")
def health(
    pool: Annotated[
        ConnectionPool | None,
        Depends(get_connection_pool),
    ],
) -> Response:
    """
    Real health check: proves the configured storage backend
    is actually reachable, not just that the process is up.

    Deliberately does not go through NodeRepository (see ADR
    0046): the shared pool's default connection timeout is 30
    seconds, correct for normal request handling but far too
    slow for a health check, which needs to fail fast on its
    own short timeout instead of inheriting one meant for
    patient, latency-tolerant callers.

    Under sqlite or memory, pool is None -- there is no
    network round-trip to hang on, so those backends are
    trivially healthy as long as the process is running at
    all.

    Returns 503, not a raised exception, on failure -- a
    healthcheck consumer (Docker, an external monitor) expects
    a status code to poll, not a stack trace.
    """
    if pool is not None:
        try:
            with pool.connection(
                timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
            ) as conn:
                conn.execute("SELECT 1")
        except Exception as exc:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unhealthy",
                    "error": type(exc).__name__,
                },
            )

    return JSONResponse(
        status_code=200,
        content={"status": "healthy"},
    )
