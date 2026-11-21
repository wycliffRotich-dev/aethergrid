"""
The composition root of the public app (ADR 0102, decision 6).

It reads the environment, opens the public pool and gives the app a
lifespan that closes the pool once when the app stops. It imports only
modules of app.infrastructure.public_read, never psycopg_pool, so the
pool is typed by the one method this file uses. It also builds the
reader of the routes on that pool.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from typing import Protocol

from fastapi import FastAPI

from app.infrastructure.public_read.postgres_public_reader import PostgresPublicReader
from app.infrastructure.public_read.public_pool import open_public_pool
from app.presentation.public.app import create_public_app
from app.presentation.public.settings import (
    DATABASE_PASSWORD_FILE_SETTING,
    PublicSettings,
)


class ClosablePool(Protocol):
    def close(self) -> None: ...


def _close_pool_on_exit(
    pool: ClosablePool,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            pool.close()

    return lifespan


def create_app(environment: Mapping[str, str] | None = None) -> FastAPI:
    source = os.environ if environment is None else environment
    settings = PublicSettings.from_environment(source)
    pool = open_public_pool(
        settings.database_url,
        settings.database_password_file,
        DATABASE_PASSWORD_FILE_SETTING,
    )
    try:
        reader = PostgresPublicReader(pool)
        return create_public_app(
            settings, lifespan=_close_pool_on_exit(pool), reader=reader
        )
    except BaseException:
        # A failing close must not hide the error that stopped construction.
        with suppress(Exception):
            pool.close()
        raise
