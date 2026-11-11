"""
Settings of the public app (ADR 0094).

Every value is required and nothing has a default, so the app cannot start
half configured. A request never chooses any of them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.domain.value_objects.tenant_id import TenantId

TENANT_SETTING = "AETHERGRID_PUBLIC_TENANT_ID"
ORIGIN_SETTING = "AETHERGRID_PUBLIC_ALLOWED_ORIGIN"

_LOCAL_HOSTS = {"localhost", "127.0.0.1"}


@dataclass(frozen=True, slots=True)
class PublicSettings:
    tenant_id: TenantId
    allowed_origin: str

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> PublicSettings:
        return cls(
            tenant_id=_tenant(environment.get(TENANT_SETTING, "")),
            allowed_origin=_origin(environment.get(ORIGIN_SETTING, "")),
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
