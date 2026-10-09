from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.exceptions.node_tenant_conflict_error import (
    NodeTenantConflictError,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.sqlite_connection import (
    create_connection,
)
from app.infrastructure.repositories.sqlite_node_repository import (
    SqliteNodeRepository,
)
from tests.support.nodes import make_node

# The nodes table exactly as it was before ADR 0064 added a tenant.
_PRE_TENANT_TABLE = """
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    capacity_cpu_cores INTEGER NOT NULL,
    capacity_memory_mib INTEGER NOT NULL,
    capacity_vram_mib INTEGER NOT NULL,
    available_cpu_cores INTEGER NOT NULL,
    available_memory_mib INTEGER NOT NULL,
    available_vram_mib INTEGER NOT NULL,
    labels TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    draining INTEGER NOT NULL
);
"""


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "nodes.db")


def test_a_saved_node_keeps_its_tenant(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteNodeRepository(connection)
    tenant_id = TenantId.new()
    node = make_node(tenant_id=tenant_id)

    repository.save(node)

    fetched = repository.get_by_id(node.id, tenant_id)
    connection.close()
    assert fetched is not None
    assert fetched.tenant_id == tenant_id


def test_saving_a_node_id_held_by_another_tenant_conflicts(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteNodeRepository(connection)
    node = make_node()
    repository.save(node)
    intruder = make_node(
        id=node.id,
        tenant_id=TenantId.new(),
        name="intruder",
    )

    with pytest.raises(NodeTenantConflictError):
        repository.save(intruder)

    stored = repository.get_by_id(node.id, DEFAULT_TENANT_ID)
    connection.close()
    assert stored is not None
    assert stored.tenant_id == DEFAULT_TENANT_ID
    assert stored.name == node.name


def test_upgrade_assigns_pre_tenant_rows_to_the_default_tenant(
    db_path,
) -> None:
    node_id = NodeId.new()
    raw = sqlite3.connect(db_path)
    raw.execute(_PRE_TENANT_TABLE)
    raw.execute(
        "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(node_id),
            "old-node",
            4,
            8192,
            0,
            4,
            8192,
            0,
            "{}",
            datetime.now(UTC).isoformat(),
            0,
        ),
    )
    raw.commit()
    raw.close()

    connection = create_connection(db_path)
    SqliteNodeRepository(connection)
    connection.close()

    # Opening an already upgraded file again changes nothing.
    connection = create_connection(db_path)
    repository = SqliteNodeRepository(connection)

    fetched = repository.get_by_id(node_id, DEFAULT_TENANT_ID)
    connection.close()
    assert fetched is not None
    assert fetched.tenant_id == DEFAULT_TENANT_ID
    assert fetched.name == "old-node"


def test_across_tenants_reads_see_nodes_in_every_tenant(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteNodeRepository(connection)
    mine = make_node()
    theirs = make_node(tenant_id=TenantId.new())
    repository.save(mine)
    repository.save(theirs)

    listed = repository.list_across_tenants()
    fetched = repository.get_by_id_across_tenants(theirs.id)
    missing = repository.get_by_id_across_tenants(NodeId.new())
    connection.close()

    assert {node.id for node in listed} == {mine.id, theirs.id}
    assert fetched is not None
    assert fetched.tenant_id == theirs.tenant_id
    assert missing is None


def test_list_available_across_tenants_skips_draining_nodes(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteNodeRepository(connection)
    ready = make_node(tenant_id=TenantId.new())
    draining = make_node(draining=True)
    repository.save(ready)
    repository.save(draining)

    available = {
        node.id for node in repository.list_available_across_tenants()
    }
    connection.close()

    assert ready.id in available
    assert draining.id not in available


def test_get_by_id_in_another_tenant_returns_none(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteNodeRepository(connection)
    other_tenant = TenantId.new()
    node = make_node()
    repository.save(node)

    foreign = repository.get_by_id(node.id, other_tenant)
    own = repository.get_by_id(node.id, DEFAULT_TENANT_ID)
    connection.close()

    assert foreign is None
    assert own is not None


def test_list_returns_only_the_callers_tenant(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteNodeRepository(connection)
    other_tenant = TenantId.new()
    mine = make_node()
    theirs = make_node(tenant_id=other_tenant)
    repository.save(mine)
    repository.save(theirs)

    own = repository.list(DEFAULT_TENANT_ID)
    foreign = repository.list(other_tenant)
    connection.close()

    assert {node.id for node in own} == {mine.id}
    assert {node.id for node in foreign} == {theirs.id}


def test_delete_in_another_tenant_leaves_the_node(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteNodeRepository(connection)
    node = make_node()
    repository.save(node)

    repository.delete(node.id, TenantId.new())

    stored = repository.get_by_id(node.id, DEFAULT_TENANT_ID)
    connection.close()
    assert stored is not None
