"""Command line entry point for applying migrations (ADR 0071).

Run as: python -m app.infrastructure.migrations
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import psycopg

from app.infrastructure.database_credentials import (
    URL_ENV,
    resolve_database_password,
)
from app.infrastructure.migrations.runner import (
    MIGRATIONS_DIR,
    MigrationError,
    apply_migrations,
    load_migrations,
)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NOT_STARTED = 2


def main(
    env: Mapping[str, str] | None = None,
    directory: Path = MIGRATIONS_DIR,
) -> int:
    """
    Apply the migrations in directory to the database named by env
    (os.environ when None) and return the process exit code.

    Reads URL_ENV and, through resolve_database_password, an optional
    password file. A password found in the file is passed to
    apply_migrations as connect_kwargs={"password": ...} and never
    printed or put in the URL.

    Prints "applied <file>" per applied migration, or "nothing to
    apply", on stdout. Errors go to stderr.

    Returns EXIT_NOT_STARTED (2) for a problem found before any
    database work: URL missing, a password file that cannot be used,
    or a migration set that cannot be loaded. Returns EXIT_FAILED (1)
    for a failure while running, including an unreachable database.
    Returns EXIT_OK (0) otherwise.
    """
    environ = os.environ if env is None else env

    url = environ.get(URL_ENV)
    if not url:
        return _fail(f"{URL_ENV} is not set", EXIT_NOT_STARTED)

    try:
        password = resolve_database_password(url, environ)
    except RuntimeError as error:
        return _fail(str(error), EXIT_NOT_STARTED)

    try:
        migrations = load_migrations(directory)
    except MigrationError as error:
        return _fail(str(error), EXIT_NOT_STARTED)

    connect_kwargs: dict[str, Any] = {}
    if password is not None:
        connect_kwargs["password"] = password

    try:
        applied = apply_migrations(url, migrations, connect_kwargs=connect_kwargs)
    except (MigrationError, psycopg.Error) as error:
        return _fail(str(error), EXIT_FAILED)

    names = {migration.version: migration.name for migration in migrations}
    for version in applied:
        print(f"applied {names[version]}")
    if not applied:
        print("nothing to apply")

    return EXIT_OK


def _fail(message: str, code: int) -> int:
    print(f"migrate: {message}", file=sys.stderr)
    return code
