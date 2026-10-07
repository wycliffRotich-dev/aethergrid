from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.value_objects.tenant_id import TenantId


def utc_now() -> datetime:
    return datetime.now(UTC)


DEFAULT_TENANT_ID = TenantId(
    "00000000-0000-0000-0000-000000000001",
)
"""
The tenant that owns every record created before tenancy
existed (ADR 0064). It is a fixed id so the schema upgrade can
create it idempotently and assign pre-tenant rows to it. The
schema upgrade that uses it is a later commit on this branch,
and that commit adds the test pinning schema.sql to this id.
"""

DEFAULT_TENANT_NAME = "default"


@dataclass(frozen=True, slots=True)
class Tenant:
    """
    The isolation boundary: a set of API keys and the
    resources they may touch, with no path to any other
    tenant's resources (ADR 0064).

    Immutable. A tenant's id and name are fixed at creation.
    """

    id: TenantId
    name: str
    created_at: datetime = field(
        default_factory=utc_now,
    )

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError(
                "tenant name must be a non-empty, "
                "human-readable identifier"
            )

    @classmethod
    def create(cls, name: str) -> Tenant:
        """
        Create a new tenant with a fresh id.

        Surrounding whitespace is trimmed before validation, so
        a name of only whitespace is rejected.
        """
        return cls(
            id=TenantId.new(),
            name=(name or "").strip(),
        )
