"""
ADR 0094. The public process reads its own database settings and never
falls back to the private ones, so it cannot pick up write credentials by
accident.
"""

from __future__ import annotations

import pytest

from app.presentation.public.settings import PublicSettings

TENANT = "11111111-1111-1111-1111-111111111111"
ORIGIN = "https://demo.example.org"
URL = "postgresql://aethergrid_public@db.internal:5432/aethergrid"
PASSWORD_FILE = "/run/secrets/public_db_password"


def _environment(**overrides: str) -> dict[str, str]:
    environment = {
        "AETHERGRID_PUBLIC_TENANT_ID": TENANT,
        "AETHERGRID_PUBLIC_ALLOWED_ORIGIN": ORIGIN,
        "AETHERGRID_PUBLIC_DATABASE_URL": URL,
        "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE": PASSWORD_FILE,
    }
    environment.update(overrides)

    return {name: value for name, value in environment.items() if value != ""}


def test_the_database_settings_are_read() -> None:
    settings = PublicSettings.from_environment(_environment())

    assert settings.database_url == URL
    assert settings.database_password_file == PASSWORD_FILE


def test_a_missing_database_url_stops_construction() -> None:
    with pytest.raises(ValueError, match="AETHERGRID_PUBLIC_DATABASE_URL"):
        PublicSettings.from_environment(_environment(AETHERGRID_PUBLIC_DATABASE_URL=""))


def test_a_missing_password_file_stops_construction() -> None:
    with pytest.raises(ValueError, match="AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE"):
        PublicSettings.from_environment(
            _environment(AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE="")
        )


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///demo.db",
        "mysql://u@h/db",
        "postgresql://",
        "db.internal:5432/aethergrid",
    ],
)
def test_a_url_that_is_not_a_postgres_url_stops_construction(url: str) -> None:
    with pytest.raises(ValueError, match="AETHERGRID_PUBLIC_DATABASE_URL"):
        PublicSettings.from_environment(_environment(AETHERGRID_PUBLIC_DATABASE_URL=url))


def test_a_password_inside_the_url_stops_construction() -> None:
    url = "postgresql://aethergrid_public:hunter2@db.internal:5432/aethergrid"

    with pytest.raises(ValueError, match="AETHERGRID_PUBLIC_DATABASE_URL"):
        PublicSettings.from_environment(_environment(AETHERGRID_PUBLIC_DATABASE_URL=url))


def test_the_private_variables_are_never_used_as_a_fallback() -> None:
    environment = {
        "AETHERGRID_PUBLIC_TENANT_ID": TENANT,
        "AETHERGRID_PUBLIC_ALLOWED_ORIGIN": ORIGIN,
        "NEUROMESH_DATABASE_URL": "postgresql://neuromesh@db.internal:5432/neuromesh",
        "NEUROMESH_DATABASE_PASSWORD_FILE": "/run/secrets/postgres_password",
    }

    with pytest.raises(ValueError, match="AETHERGRID_PUBLIC_DATABASE_URL"):
        PublicSettings.from_environment(environment)


def test_the_error_does_not_print_the_password_in_the_url() -> None:
    url = "postgresql://aethergrid_public:hunter2@db.internal:5432/aethergrid"

    with pytest.raises(ValueError) as caught:
        PublicSettings.from_environment(_environment(AETHERGRID_PUBLIC_DATABASE_URL=url))

    assert "hunter2" not in str(caught.value)


def test_the_repr_does_not_print_the_database_settings() -> None:
    shown = repr(PublicSettings.from_environment(_environment()))

    assert URL not in shown
    assert PASSWORD_FILE not in shown
