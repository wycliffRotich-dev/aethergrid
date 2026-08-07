from __future__ import annotations

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
