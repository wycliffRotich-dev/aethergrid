from __future__ import annotations

import re
from pathlib import Path

from app.domain.entities.tenant import (
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_NAME,
)
from app.domain.value_objects.tenant_id import TenantId

SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "app/infrastructure/repositories/schema.sql"
).read_text()


def test_schema_default_tenant_matches_the_domain_constants():
    match = re.search(
        r"INSERT INTO tenants \(id, name, created_at\)\s+"
        r"VALUES \('([0-9a-f-]+)',\s*'([^']+)'",
        SCHEMA,
        re.IGNORECASE,
    )

    assert match is not None, "schema.sql has no default tenant insert"
    assert TenantId(match.group(1)) == DEFAULT_TENANT_ID
    assert match.group(2) == DEFAULT_TENANT_NAME


def test_tenants_table_is_created_before_any_resource_table():
    assert SCHEMA.index("CREATE TABLE IF NOT EXISTS tenants") < (
        SCHEMA.index("CREATE TABLE IF NOT EXISTS nodes")
    )
