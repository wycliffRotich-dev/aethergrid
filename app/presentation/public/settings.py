"""
Settings of the public app (ADR 0094).

Every value is required and nothing has a default, so the app cannot start
half configured. A request never chooses any of them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.domain.value_objects.tenant_id import TenantId

TENANT_SETTING = "AETHERGRID_PUBLIC_TENANT_ID"
ORIGIN_SETTING = "AETHERGRID_PUBLIC_ALLOWED_ORIGIN"
DATABASE_URL_SETTING = "AETHERGRID_PUBLIC_DATABASE_URL"
DATABASE_PASSWORD_FILE_SETTING = "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE"

_LOCAL_HOSTS = {"localhost", "127.0.0.1"}


@dataclass(frozen=True, slots=True)
class PublicSettings:
    tenant_id: TenantId
    allowed_origin: str
    # Kept out of repr so a log line of the settings never shows them.
    database_url: str = field(repr=False)
    database_password_file: str = field(repr=False)

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> PublicSettings:
        return cls(
            tenant_id=_tenant(environment.get(TENANT_SETTING, "")),
            allowed_origin=_origin(environment.get(ORIGIN_SETTING, "")),
            database_url=_database_url(environment.get(DATABASE_URL_SETTING, "")),
            database_password_file=_password_file(
                environment.get(DATABASE_PASSWORD_FILE_SETTING, "")
            ),
        )


def _tenant(raw: str) -> TenantId:
    try:
        return TenantId.from_string(raw.strip())
    except ValueError as error:
        raise ValueError(f"{TENANT_SETTING} must be a tenant UUID") from error


def _origin(raw: str) -> str:
    parts = urlsplit(raw.strip())
    host = parts.hostname or ""
    secure = parts.scheme == "https"
    local = parts.scheme == "http" and host in _LOCAL_HOSTS
    bare = parts.path in {"", "/"} and not (parts.query or parts.fragment)

    if not (host and bare and (secure or local)) or "*" in raw:
        raise ValueError(
            f"{ORIGIN_SETTING} must be one origin such as https://demo.example.org"
        )

    port = f":{parts.port}" if parts.port else ""

    return f"{parts.scheme}://{host}{port}"


def _database_url(raw: str) -> str:
    url = raw.strip()
    parts = urlsplit(url)

    if parts.scheme not in {"postgresql", "postgres"} or not parts.hostname:
        raise ValueError(
            f"{DATABASE_URL_SETTING} must be a postgresql:// URL with a host"
        )

    if parts.password:
        # The message names the setting only. It never repeats the URL.
        raise ValueError(
            f"{DATABASE_URL_SETTING} must not contain a password, "
            f"use {DATABASE_PASSWORD_FILE_SETTING}"
        )

    return url


def _password_file(raw: str) -> str:
    path = raw.strip()

    if not path:
        raise ValueError(f"{DATABASE_PASSWORD_FILE_SETTING} must name a file")

    return path
