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


def open_public_pool(
    database_url: str, password_file: str, password_file_setting: str
) -> ConnectionPool:
    check_database_url(database_url)
    password = read_password_file(password_file, password_file_setting)

    return ConnectionPool(
        database_url, open=False, kwargs={"password": password}
    )
