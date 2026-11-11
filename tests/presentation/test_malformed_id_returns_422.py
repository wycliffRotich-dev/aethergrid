"""
A malformed id in the URL is the caller's mistake and answers 422.

The worker routes already did this. The API key, job and node routes
passed the raw string to UUID(), so a typo raised an unhandled
ValueError: a 500, and a traceback in the error log for what is a
client error.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.presentation.api import app
from app.presentation.auth import require_api_key, require_rate_limit

MALFORMED = "not-a-valid-uuid"

ROUTES = [
    ("POST", f"/api-keys/{MALFORMED}/revoke", "Malformed API key id."),
    ("GET", f"/api-keys/{MALFORMED}/issued", "Malformed API key id."),
    ("GET", f"/jobs/{MALFORMED}", "Malformed job id."),
    ("POST", f"/jobs/{MALFORMED}/cancel", "Malformed job id."),
    ("POST", f"/jobs/{MALFORMED}/retry", "Malformed job id."),
    ("GET", f"/nodes/{MALFORMED}", "Malformed node id."),
    ("POST", f"/nodes/{MALFORMED}/heartbeat", "Malformed node id."),
    ("POST", f"/nodes/{MALFORMED}/drain", "Malformed node id."),
    ("DELETE", f"/nodes/{MALFORMED}", "Malformed node id."),
]


@pytest.mark.parametrize(("method", "path", "detail"), ROUTES)
def test_malformed_id_returns_422(method: str, path: str, detail: str) -> None:
    with TestClient(app) as client:
        response = client.request(method, path)

    assert response.status_code == 422
    assert response.json() == {"detail": detail}


PATHS = [(method, path) for method, path, _ in ROUTES]


@pytest.mark.parametrize(("method", "path"), PATHS)
def test_well_formed_unknown_id_is_still_a_404(method: str, path: str) -> None:
    """The 422 is for a malformed id only: an unknown one is still a 404."""
    unknown = path.replace(MALFORMED, "00000000-0000-0000-0000-000000000000")

    with TestClient(app) as client:
        response = client.request(method, unknown)

    assert response.status_code == 404


@pytest.fixture()
def no_overrides() -> Iterator[None]:
    """Put the real key check back, which conftest replaces for every test."""
    saved = {
        dep: app.dependency_overrides.pop(dep)
        for dep in (require_api_key, require_rate_limit)
        if dep in app.dependency_overrides
    }
    yield
    app.dependency_overrides.update(saved)


@pytest.mark.parametrize(("method", "path"), PATHS)
def test_malformed_id_without_a_key_is_still_a_401(
    no_overrides: None, method: str, path: str
) -> None:
    """The key is checked first, so the 422 tells an unauthenticated caller nothing."""
    with TestClient(app) as client:
        response = client.request(method, path)

    assert response.status_code == 401
