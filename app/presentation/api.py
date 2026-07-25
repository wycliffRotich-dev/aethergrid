from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.presentation.dependencies import get_cluster_tick_service
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


async def _run_cluster_loop() -> None:
    """
    Repeatedly drive the cluster forward: schedule queued
    jobs, assign idle workers, and execute assigned work.

    Runs as a background asyncio task for the lifetime of
    the application. A tick's own internal errors are
    already isolated per-worker by ClusterTickService; this
    outer try/except exists only as a last line of defense
    so a truly unexpected exception can't silently kill the
    loop without a trace.

    Note: ClusterTickService.execute() runs synchronously,
    including any real subprocess execution via
    JobExecutionService. Every job created through the
    public API today has no command (see ADR 0012), so this
    resolves instantly. If real command execution is ever
    exposed publicly, this call should move to a thread
    (e.g. via asyncio.to_thread) so a long-running job can't
    block the event loop.
    """
    cluster_tick_service = get_cluster_tick_service()

    while True:
        try:
            cluster_tick_service.execute()
        except Exception:
            logger.exception(
                "Unexpected error running cluster tick.",
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
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.get("/")
def root() -> dict[str, str]:
    """
    Health endpoint.
    """
    return {
        "message": "Welcome to NeuroMesh API",
    }
