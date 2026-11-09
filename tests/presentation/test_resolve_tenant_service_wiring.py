from __future__ import annotations

from uuid import uuid4

from app.presentation.dependencies import (
    get_create_api_key_service,
    get_resolve_tenant_service,
)

# ADR 0090: --create-tenant and key issuance run in one process, so the
# two services must read and write one tenant store. A resolver wired to
# its own repository would create a tenant the key service cannot see,
# and only the memory backend would show it.


def test_a_tenant_created_by_the_resolver_can_receive_a_key() -> None:
    name = f"wiring-{uuid4().hex}"

    resolved = get_resolve_tenant_service().execute(
        name,
        create_if_missing=True,
    )
    issued = get_create_api_key_service().execute(
        label="wiring-check",
        tenant_id=resolved.tenant.id,
    )

    assert issued.label == "wiring-check"
