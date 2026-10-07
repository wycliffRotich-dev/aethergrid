from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

from app.domain.entities.tenant import (
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_NAME,
)

HERE = Path(__file__).resolve().parent
CURRENT_SCHEMA = (
    HERE.parents[1] / "app/infrastructure/repositories/schema.sql"
).read_text()
PRE_TENANCY_SCHEMA = (HERE / "schema_pre_tenancy.sql").read_text()


@pytest.fixture
def scratch(test_database_url):
    """
    A throwaway Postgres schema, so an upgrade can be replayed from
    a frozen older schema without touching the real test tables.
    """
    name = f"upgrade_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(test_database_url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{name}"')
        conn.execute(f'SET search_path TO "{name}"')
        try:
            yield conn
        finally:
            conn.execute("SET search_path TO public")
            conn.execute(f'DROP SCHEMA "{name}" CASCADE')


def _tenants(conn):
    return conn.execute("SELECT id::text, name FROM tenants").fetchall()


def test_a_fresh_schema_contains_the_default_tenant(scratch):
    scratch.execute(CURRENT_SCHEMA)

    assert _tenants(scratch) == [
        (str(DEFAULT_TENANT_ID), DEFAULT_TENANT_NAME)
    ]


def test_upgrading_a_pre_tenancy_database_adds_the_default_tenant(
    scratch,
):
    scratch.execute(PRE_TENANCY_SCHEMA)

    with pytest.raises(psycopg.errors.UndefinedTable):
        _tenants(scratch)

    scratch.execute(CURRENT_SCHEMA)

    assert _tenants(scratch) == [
        (str(DEFAULT_TENANT_ID), DEFAULT_TENANT_NAME)
    ]


def test_upgrading_keeps_rows_that_already_exist(scratch):
    scratch.execute(PRE_TENANCY_SCHEMA)
    node_id = str(uuid.uuid4())
    scratch.execute(
        """
        INSERT INTO nodes (
            id, name, capacity_cpu_cores, capacity_memory_mib,
            capacity_vram_mib, available_cpu_cores,
            available_memory_mib, available_vram_mib, last_seen_at
        ) VALUES (%s, 'old-node', 8, 16384, 0, 8, 16384, 0, now())
        """,
        (node_id,),
    )

    scratch.execute(CURRENT_SCHEMA)

    rows = scratch.execute(
        "SELECT id::text, name FROM nodes"
    ).fetchall()
    assert rows == [(node_id, "old-node")]


def test_applying_the_schema_again_changes_nothing(scratch):
    scratch.execute(CURRENT_SCHEMA)
    scratch.execute(CURRENT_SCHEMA)
    scratch.execute(CURRENT_SCHEMA)

    assert _tenants(scratch) == [
        (str(DEFAULT_TENANT_ID), DEFAULT_TENANT_NAME)
    ]
