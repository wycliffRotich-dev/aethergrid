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


def test_upgrading_assigns_existing_keys_to_the_default_tenant(scratch):
    scratch.execute(PRE_TENANCY_SCHEMA)
    key_id = str(uuid.uuid4())
    scratch.execute(
        "INSERT INTO api_keys (id, key_hash, label, created_at) "
        "VALUES (%s, %s, 'legacy', now())",
        (key_id, "hash-" + key_id),
    )

    scratch.execute(CURRENT_SCHEMA)

    rows = scratch.execute(
        "SELECT id::text, tenant_id::text FROM api_keys"
    ).fetchall()
    assert rows == [(key_id, str(DEFAULT_TENANT_ID))]


def test_a_key_must_name_a_tenant_after_the_upgrade(scratch):
    scratch.execute(CURRENT_SCHEMA)

    with pytest.raises(psycopg.errors.NotNullViolation):
        scratch.execute(
            "INSERT INTO api_keys (id, key_hash, label, created_at) "
            "VALUES (%s, 'hash-x', 'x', now())",
            (str(uuid.uuid4()),),
        )


def test_a_key_cannot_name_an_issuer_from_another_tenant(scratch):
    scratch.execute(CURRENT_SCHEMA)
    other = str(uuid.uuid4())
    issuer = str(uuid.uuid4())
    scratch.execute(
        "INSERT INTO tenants (id, name, created_at) "
        "VALUES (%s, 'other', now())",
        (other,),
    )
    scratch.execute(
        "INSERT INTO api_keys (id, key_hash, label, created_at, tenant_id) "
        "VALUES (%s, 'hash-issuer', 'issuer', now(), %s)",
        (issuer, str(DEFAULT_TENANT_ID)),
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        scratch.execute(
            "INSERT INTO api_keys "
            "(id, key_hash, label, created_at, tenant_id, issued_by) "
            "VALUES (%s, 'hash-child', 'child', now(), %s, %s)",
            (str(uuid.uuid4()), other, issuer),
        )


_NODE_WITHOUT_TENANT = (
    "INSERT INTO nodes ("
    "id, name, capacity_cpu_cores, capacity_memory_mib, "
    "capacity_vram_mib, available_cpu_cores, available_memory_mib, "
    "available_vram_mib, last_seen_at"
    ") VALUES (%s, 'n', 8, 16384, 0, 8, 16384, 0, now())"
)


def test_upgrading_assigns_existing_nodes_to_the_default_tenant(scratch):
    scratch.execute(PRE_TENANCY_SCHEMA)
    node_id = str(uuid.uuid4())
    scratch.execute(_NODE_WITHOUT_TENANT, (node_id,))

    scratch.execute(CURRENT_SCHEMA)

    rows = scratch.execute(
        "SELECT id::text, tenant_id::text FROM nodes"
    ).fetchall()
    assert rows == [(node_id, str(DEFAULT_TENANT_ID))]


def test_a_node_must_name_a_tenant_after_the_upgrade(scratch):
    scratch.execute(PRE_TENANCY_SCHEMA)
    scratch.execute(CURRENT_SCHEMA)

    with pytest.raises(psycopg.errors.NotNullViolation):
        scratch.execute(_NODE_WITHOUT_TENANT, (str(uuid.uuid4()),))


def test_a_node_must_name_a_tenant_in_a_fresh_schema(scratch):
    scratch.execute(CURRENT_SCHEMA)

    with pytest.raises(psycopg.errors.NotNullViolation):
        scratch.execute(_NODE_WITHOUT_TENANT, (str(uuid.uuid4()),))


def test_a_node_cannot_name_a_tenant_that_does_not_exist(scratch):
    scratch.execute(CURRENT_SCHEMA)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        scratch.execute(
            "INSERT INTO nodes ("
            "id, name, capacity_cpu_cores, capacity_memory_mib, "
            "capacity_vram_mib, available_cpu_cores, "
            "available_memory_mib, available_vram_mib, last_seen_at, "
            "tenant_id"
            ") VALUES (%s, 'n', 8, 16384, 0, 8, 16384, 0, now(), %s)",
            (str(uuid.uuid4()), str(uuid.uuid4())),
        )
