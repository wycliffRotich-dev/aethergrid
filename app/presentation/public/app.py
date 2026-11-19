"""
The public, read-only application (ADR 0094).

A separate FastAPI app with its own route table. It serves GET routes from
an explicit allowlist, starts no loop, and does not import the private
routers or the composition root of the private API.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.application.public_rate_limiter import AnonymousRateLimiter
from app.presentation.public.rate_limit_middleware import (
    AnonymousRateLimitMiddleware,
)
from app.presentation.public.settings import PublicSettings


def create_public_app(
    settings: PublicSettings,
    limiter: AnonymousRateLimiter | None = None,
) -> FastAPI:
    app = FastAPI(
        title="AetherGrid public demo",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
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

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
