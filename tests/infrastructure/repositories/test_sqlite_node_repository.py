from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.entities.node import Node
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.infrastructure.repositories.sqlite_connection import (
    create_connection,
)
from app.infrastructure.repositories.sqlite_node_repository import (
    SqliteNodeRepository,
)
from tests.support.nodes import make_node


@pytest.fixture()
def db_path():
    """
    Provide a real temp-file SQLite database path so tests
    prove persistence across separate connections, not just
    reads from a shared in-process connection object.
    """
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)

    yield path

    os.remove(path)


def _make_node(
    cpu_cores: int = 4,
    memory_mib: int = 4096,
    vram_mib: int = 0,
    draining: bool = False,
    last_seen_at: datetime | None = None,
) -> Node:
    return make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=cpu_cores,
            memory_mib=memory_mib,
            vram_mib=vram_mib,
        ),
        labels={"zone": "us-east"},
        last_seen_at=last_seen_at or datetime.now(UTC),
        draining=draining,
    )


def test_save_and_get_by_id_round_trips_full_node(db_path) -> None:
    node = _make_node()

    # Partially allocate so available diverges from capacity --
    # this is the field most at risk of silently reloading wrong,
    # since Node.__post_init__ resets it to capacity on construction.
    node.allocate(
        ResourceRequirements(
            cpu_cores=1,
            memory_mib=1024,
            vram_mib=0,
        ),
    )

    write_connection = create_connection(db_path)
    write_repository = SqliteNodeRepository(write_connection)
    write_repository.save(node)
    write_connection.close()

    # Fresh connection and fresh repository instance -- proves
    # the round trip survives independent of any in-memory state.
    read_connection = create_connection(db_path)
    read_repository = SqliteNodeRepository(read_connection)
    reloaded = read_repository.get_by_id(node.id, DEFAULT_TENANT_ID)
    read_connection.close()

    assert reloaded is not None
    assert reloaded.id == node.id
    assert reloaded.capacity.cpu_cores == 4
    assert reloaded.capacity.memory_mib == 4096
    assert reloaded.available.cpu_cores == 3
    assert reloaded.available.memory_mib == 3072
    assert reloaded.labels == {"zone": "us-east"}
    assert reloaded.draining is False


def test_get_by_id_returns_none_when_not_found(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteNodeRepository(connection)

    result = repository.get_by_id(NodeId.new(), DEFAULT_TENANT_ID)

    assert result is None


def test_list_returns_all_saved_nodes(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteNodeRepository(connection)

    first = _make_node()
    second = _make_node()
    repository.save(first)
    repository.save(second)

    result = repository.list(DEFAULT_TENANT_ID)

    assert {node.id for node in result} == {first.id, second.id}


def test_list_available_across_tenants_excludes_stale_nodes(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteNodeRepository(connection)

    healthy = _make_node()
    stale = _make_node(
        last_seen_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    repository.save(healthy)
    repository.save(stale)

    result = repository.list_available_across_tenants()

    assert healthy.id in {node.id for node in result}
    assert stale.id not in {node.id for node in result}


def test_delete_removes_node(db_path) -> None:
    connection = create_connection(db_path)
    repository = SqliteNodeRepository(connection)

    node = _make_node()
    repository.save(node)

    repository.delete(node.id, DEFAULT_TENANT_ID)

    assert repository.get_by_id(node.id, DEFAULT_TENANT_ID) is None


def test_save_twice_updates_existing_node_instead_of_duplicating(
    db_path,
) -> None:
    connection = create_connection(db_path)
    repository = SqliteNodeRepository(connection)

    node = _make_node()
    repository.save(node)

    node.drain()
    repository.save(node)

    result = repository.list(DEFAULT_TENANT_ID)
    matching = [n for n in result if n.id == node.id]

    assert len(matching) == 1
    assert matching[0].draining is True
