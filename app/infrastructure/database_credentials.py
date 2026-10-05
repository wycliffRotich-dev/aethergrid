"""Resolve the database password from a file, when one is configured.

NEUROMESH_DATABASE_URL carries everything except, optionally, the
password. When NEUROMESH_DATABASE_PASSWORD_FILE is set, the password
is read from that file and handed to the connection as a keyword, so
it never sits in an environment variable or inside the URL string.

With no file configured this returns None and behavior is unchanged.
A password in both places is an error, not a precedence rule: a
silent choice between two credentials is how secrets end up in places
nobody expects.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

PASSWORD_FILE_ENV = "NEUROMESH_DATABASE_PASSWORD_FILE"
URL_ENV = "NEUROMESH_DATABASE_URL"


def resolve_database_password(
    database_url: str,
    env: Mapping[str, str],
) -> str | None:
    path = env.get(PASSWORD_FILE_ENV)
    if not path:
        return None

    if urlsplit(database_url).password:
        raise RuntimeError(
            f"{URL_ENV} already contains a password and "
            f"{PASSWORD_FILE_ENV} is also set. Use one or the "
            f"other: remove the password from the URL to read it "
            f"from the file."
        )

    try:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
    except OSError as error:
        raise RuntimeError(
            f"{PASSWORD_FILE_ENV} points at '{path}', which could "
            f"not be read: {error.strerror or type(error).__name__}."
        ) from None

    password = raw[:-1] if raw.endswith("\n") else raw
    if not password:
        raise RuntimeError(
            f"{PASSWORD_FILE_ENV} points at '{path}', which is empty."
        )
    return password
