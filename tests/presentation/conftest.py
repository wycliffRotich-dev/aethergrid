from __future__ import annotations

import os

import pytest

from app.domain.entities.api_key import ApiKey
from app.presentation.api import app
from app.presentation.auth import require_api_key


@pytest.fixture(autouse=True)
def bypass_api_key_auth():
    """
    Presentation-layer tests exercise route behavior (status
    codes, response shape, whether a field is exposed), not the
    auth flow itself -- that's already covered by
    tests/application/test_authenticate_api_key_service.py and
    the request-level checks that validated require_api_key
    directly. Overriding the dependency here keeps every test
    in this directory focused on what it was actually written
    to verify, instead of every one of them needing to carry a
    bearer token that has nothing to do with what they're
    testing.

    Scoped to tests/presentation/ only, by virtue of where this
    file lives -- tests elsewhere still exercise the real auth
    gate.
    """
    fake_caller, _raw_key = ApiKey.issue(label="test-suite")
    app.dependency_overrides[require_api_key] = lambda: fake_caller
    yield
    app.dependency_overrides.pop(require_api_key, None)


@pytest.fixture(autouse=True)
def reset_repositories():
    """
    dependencies.py builds its repositories once, as module-
    level singletons, at process import time. Every TestClient
    instantiated across this entire test file, and every other
    file in tests/presentation/, shares those same objects,
    regardless of which backend is active.

    Without this, state from one test (nodes, jobs, workers it
    created) silently leaks into every test that runs after it
    in the same pytest session -- a job created in this test
    can get scheduled onto some earlier test's leftover node
    with no idle worker on it, producing a failure that has
    nothing to do with the test actually being run.

    Branches on NEUROMESH_STORAGE_BACKEND rather than assuming
    in-memory: the in-memory repositories expose clear(), but
    when the backend is postgres, dependencies.py builds real
    PostgresJobRepository/PostgresNodeRepository/
    PostgresWorkerRepository instances instead, which have no
    such method and share one live database across the whole
    suite. TRUNCATE is the same approach the Postgres contract
    tests already use for the same reason (see
    tests/infrastructure/repositories/test_postgres_job_repository_contract.py).

    Scoped to tests/presentation/ only, by virtue of where this
    file lives.
    """
    from app.presentation.dependencies import (
        _job_repository,
        _node_repository,
        _worker_repository,
    )

    backend = os.getenv(
        "NEUROMESH_STORAGE_BACKEND",
        "memory",
    ).lower()

    def _reset() -> None:
        if backend == "postgres":
            with _job_repository._pool.connection() as conn:
                conn.execute(
                    "TRUNCATE jobs, nodes, workers, leases CASCADE"
                )
        else:
            _job_repository.clear()
            _node_repository.clear()
            _worker_repository.clear()

    _reset()
    yield
    _reset()
