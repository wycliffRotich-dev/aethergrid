"""
ADR 0103, decision 5. The number of trusted proxy hops is required, has no
default and is an integer from 0 to 5. A wrong value lets a caller choose
the address that is used to count them, so the value is parsed strictly.
"""

from __future__ import annotations

import pytest

from app.presentation.public.settings import PublicSettings

ORIGIN = "https://demo.example.org"
URL = "postgresql://aethergrid_public@db.internal:5432/aethergrid"
PASSWORD_FILE = "/run/secrets/public_db_password"
SETTING = "AETHERGRID_PUBLIC_TRUSTED_PROXY_HOPS"


def _environment(**overrides: str) -> dict[str, str]:
    environment = {
        "AETHERGRID_PUBLIC_ALLOWED_ORIGIN": ORIGIN,
        "AETHERGRID_PUBLIC_DATABASE_URL": URL,
        "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE": PASSWORD_FILE,
        SETTING: "1",
    }
    environment.update(overrides)

    return {name: value for name, value in environment.items() if value != ""}


@pytest.mark.parametrize("raw", ["0", "1", "2", "3", "4", "5"])
def test_each_count_from_zero_to_five_is_read(raw: str) -> None:
    settings = PublicSettings.from_environment(_environment(**{SETTING: raw}))

    assert settings.trusted_proxy_hops == int(raw)


def test_surrounding_whitespace_is_ignored() -> None:
    settings = PublicSettings.from_environment(_environment(**{SETTING: " 2 "}))

    assert settings.trusted_proxy_hops == 2


def test_a_missing_count_stops_construction() -> None:
    with pytest.raises(ValueError, match=SETTING):
        PublicSettings.from_environment(_environment(**{SETTING: ""}))


def test_a_blank_count_stops_construction() -> None:
    with pytest.raises(ValueError, match=SETTING):
        PublicSettings.from_environment(_environment(**{SETTING: "   "}))


@pytest.mark.parametrize(
    "raw",
    [
        "6",
        "10",
        "100",
        "-1",
        "+1",
        "01",
        "00",
        "1.0",
        "1.5",
        "1_0",
        "0x1",
        "1e0",
        "two",
        "1 2",
        "1,2",
        "true",
        "\u0663",
        "\u00b2",
        "\uff11",
    ],
)
def test_a_value_that_is_not_a_plain_count_from_zero_to_five_is_refused(
    raw: str,
) -> None:
    with pytest.raises(ValueError, match=SETTING):
        PublicSettings.from_environment(_environment(**{SETTING: raw}))


def test_the_count_is_never_taken_from_another_setting() -> None:
    environment = _environment(**{SETTING: ""})
    environment["NEUROMESH_TRUSTED_PROXY_HOPS"] = "1"
    environment["TRUSTED_PROXY_HOPS"] = "1"

    with pytest.raises(ValueError, match=SETTING):
        PublicSettings.from_environment(environment)
