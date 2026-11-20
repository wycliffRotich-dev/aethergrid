"""
The URL check of the public database pool (ADR 0104, decisions 2 and 3).

The URL is read the way libpq reads it, so the check sees what a connection
would use. Only listed keys pass, the user must be the public app role, and a
hash sign in the database name is refused. Every refusal raises one fixed
message that holds no part of the URL. It is raised before the password file
is read and before a pool exists.
"""

from __future__ import annotations

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg_pool import ConnectionPool

from app.infrastructure.database_credentials import read_password_file

PUBLIC_APP_ROLE = "aethergrid_public_app"
ALLOWED_KEYS = frozenset({"host", "port", "dbname", "user", "sslmode", "sslrootcert"})
URL_SCHEMES = ("postgresql://", "postgres://")
# ADR 0102, decision 3. The timeout is the two seconds of /health (ADR 0046),
# so an anonymous caller does not hold a thread longer than a probe does.
POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 5
POOL_TIMEOUT_SECONDS = 2.0
STATEMENT_TIMEOUT_MS = 2000
# The first connection is made at start, so it may need a TLS handshake. It
# is not the wait of a visitor, which is POOL_TIMEOUT_SECONDS.
STARTUP_TIMEOUT_SECONDS = 5.0
CONNECTION_SETTINGS = (
    ("statement_timeout", str(STATEMENT_TIMEOUT_MS)),
    ("default_transaction_read_only", "on"),
)
REFUSAL = "the database URL of the public pool is not accepted"


def _is_accepted(database_url: str) -> bool:
    if not database_url.startswith(URL_SCHEMES):
        return False

    try:
        parts = conninfo_to_dict(database_url)
    except psycopg.Error:
        return False

    return (
        set(parts) <= ALLOWED_KEYS
        and parts.get("user") == PUBLIC_APP_ROLE
        and "#" not in str(parts.get("dbname", ""))
    )


def check_database_url(database_url: str) -> None:
    if not _is_accepted(database_url):
        raise ValueError(REFUSAL) from None


def _close_quietly(pool: ConnectionPool) -> None:
    try:
        pool.close()
    except Exception:
        return None


def open_public_pool(
    database_url: str, password_file: str, password_file_setting: str
) -> ConnectionPool:
    check_database_url(database_url)
    password = read_password_file(password_file, password_file_setting)

    options = " ".join(f"-c {name}={value}" for name, value in CONNECTION_SETTINGS)

    pool = ConnectionPool(
        database_url,
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
        timeout=POOL_TIMEOUT_SECONDS,
        open=False,
        kwargs={"password": password, "autocommit": True, "options": options},
    )
    failed = False

    try:
        pool.open(wait=True, timeout=STARTUP_TIMEOUT_SECONDS)
    except Exception:
        failed = True

    if failed:
        _close_quietly(pool)
        raise RuntimeError(
            "the public database pool could not open its first connection, "
            f"check the database URL and {password_file_setting}"
        ) from None

    return pool
