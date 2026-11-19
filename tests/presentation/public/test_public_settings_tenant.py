"""
The tenant of the public demo lives in the database, not in the settings
(ADR 0102, decision 8). The app cannot read public_demo_scope, so a tenant
setting could only disagree with it without anyone noticing.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.presentation.public.settings import (
    DATABASE_PASSWORD_FILE_SETTING,
    DATABASE_URL_SETTING,
    ORIGIN_SETTING,
    PROXY_HOPS_SETTING,
    PublicSettings,
)

REMOVED_SETTING = "AETHERGRID_PUBLIC_TENANT_ID"
ORIGIN = "https://demo.example.org"
DATABASE_URL = "postgresql://aethergrid_public@127.0.0.1:5433/aethergrid"
PASSWORD_FILE = "/run/secrets/public_password"


def _environment() -> dict[str, str]:
    return {
        ORIGIN_SETTING: ORIGIN,
        DATABASE_URL_SETTING: DATABASE_URL,
        DATABASE_PASSWORD_FILE_SETTING: PASSWORD_FILE,
        PROXY_HOPS_SETTING: "1",
    }


def test_the_settings_need_no_tenant() -> None:
    settings = PublicSettings.from_environment(_environment())

    assert settings.allowed_origin == ORIGIN


def test_the_settings_hold_no_tenant() -> None:
    names = {field.name for field in dataclasses.fields(PublicSettings)}

    assert "tenant_id" not in names


@pytest.mark.parametrize(
    "stale_value",
    ["11111111-1111-1111-1111-111111111111", "not-a-uuid", ""],
)
def test_a_stale_tenant_variable_changes_nothing(stale_value: str) -> None:
    environment = _environment()
    expected = PublicSettings.from_environment(environment)

    environment[REMOVED_SETTING] = stale_value

    assert PublicSettings.from_environment(environment) == expected
