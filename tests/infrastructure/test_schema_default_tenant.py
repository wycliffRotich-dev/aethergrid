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


def test_schema_backfills_keys_into_the_default_tenant():
    match = re.search(
        r"UPDATE api_keys\s+SET tenant_id = '([0-9a-f-]+)'",
        SCHEMA,
        re.IGNORECASE,
    )

    assert match is not None, "schema.sql has no key backfill"
    assert TenantId(match.group(1)) == DEFAULT_TENANT_ID


def test_the_key_tenant_column_never_has_a_default():
    match = re.search(
        r"ALTER TABLE api_keys\s+ADD COLUMN IF NOT EXISTS tenant_id[^;]*;",
        SCHEMA,
        re.IGNORECASE,
    )

    assert match is not None, "schema.sql does not add api_keys.tenant_id"
    assert "DEFAULT" not in match.group(0).upper()
