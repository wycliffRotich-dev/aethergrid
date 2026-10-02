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
