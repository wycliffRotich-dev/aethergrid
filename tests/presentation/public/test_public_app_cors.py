"""ADR 0094. Only the configured origin is allowed, and never with credentials."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.presentation.public.app import create_public_app
from app.presentation.public.settings import PublicSettings

ORIGIN = "https://demo.example.org"


def _client() -> TestClient:
    settings = PublicSettings.from_environment(
        {
            "AETHERGRID_PUBLIC_TENANT_ID": "11111111-1111-1111-1111-111111111111",
            "AETHERGRID_PUBLIC_ALLOWED_ORIGIN": ORIGIN,
            "AETHERGRID_PUBLIC_DATABASE_URL": "postgresql://aethergrid_public@db.internal:5432/aethergrid",
            "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE": "/run/secrets/public_db_password",
        }
    )

    return TestClient(create_public_app(settings))


def test_the_configured_origin_is_allowed() -> None:
    response = _client().get("/healthz", headers={"Origin": ORIGIN})

    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_another_origin_is_not_allowed() -> None:
    response = _client().get("/healthz", headers={"Origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers


def test_credentials_are_never_allowed() -> None:
    response = _client().get("/healthz", headers={"Origin": ORIGIN})

    assert "access-control-allow-credentials" not in response.headers


def test_a_preflight_for_a_write_method_is_refused() -> None:
    response = _client().options(
        "/healthz",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 400
