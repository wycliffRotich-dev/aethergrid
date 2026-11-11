"""
The public, read-only application (ADR 0094).

A separate FastAPI app with its own route table. It serves GET routes from
an explicit allowlist, starts no loop, and does not import the private
routers or the composition root of the private API.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.presentation.public.settings import PublicSettings


def create_public_app(settings: PublicSettings) -> FastAPI:
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

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
