"""Keep the test suite away from any database that is not a test database.

The app builds its Postgres pool when app.presentation.dependencies is
first imported, reading NEUROMESH_DATABASE_URL at that moment. The
presentation fixtures run TRUNCATE ... CASCADE on that pool. This file
loads before any test module, so it can point the app at the test
database before the pool exists.
"""

import os
from urllib.parse import urlparse

import pytest

from app.infrastructure.database_credentials import (
    resolve_database_password,
)


def _database_name(url: str) -> str:
    return urlparse(url).path.lstrip("/")


if os.environ.get("NEUROMESH_STORAGE_BACKEND", "").lower() == "postgres":
    test_url = os.environ.get("NEUROMESH_TEST_DATABASE_URL")
    if not test_url:
        raise pytest.UsageError(
            "NEUROMESH_STORAGE_BACKEND is postgres but "
            "NEUROMESH_TEST_DATABASE_URL is not set. Refusing to run."
        )
    if not _database_name(test_url).endswith("_test"):
        raise pytest.UsageError(
            "NEUROMESH_TEST_DATABASE_URL must point at a database whose "
            "name ends in _test. Refusing to run."
        )
    os.environ["NEUROMESH_DATABASE_URL"] = test_url


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Return the test database URL, or fail with one clear message."""
    url = os.environ.get("NEUROMESH_TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "NEUROMESH_TEST_DATABASE_URL is not set. Point it at a "
            "database whose name ends in _test (see README).",
            pytrace=False,
        )
    if not _database_name(url).endswith("_test"):
        pytest.fail(
            "NEUROMESH_TEST_DATABASE_URL must point at a database whose "
            "name ends in _test. Refusing to run.",
            pytrace=False,
        )
    return url


@pytest.fixture(scope="session", autouse=True)
def database_password_from_file() -> None:
    """Expose a file-based database password to libpq for the whole run.

    When NEUROMESH_DATABASE_PASSWORD_FILE is set, the password is read
    through the same helper the application uses and handed to every
    connection via PGPASSWORD, so the Postgres tests authenticate
    without a password in any URL. With no file configured this does
    nothing.
    """
    url = os.environ.get("NEUROMESH_TEST_DATABASE_URL", "")
    password = resolve_database_password(url, os.environ)
    if password is not None:
        os.environ["PGPASSWORD"] = password
