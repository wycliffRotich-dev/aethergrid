from __future__ import annotations

import pytest

from scripts.upgrade_rehearsal import Snapshot, compare_snapshots

WORKERS = "id,node_id,tenant_id\nw1,n1,t1\nw2,n1,t1\n"
NODES = "id,name\nn1,rehearsal-node\n"


def snapshot(workers: str = WORKERS, nodes: str = NODES) -> Snapshot:
    return {"nodes": nodes, "workers": workers}


def test_identical_snapshots_have_no_differences() -> None:
    assert compare_snapshots(snapshot(), snapshot()) == []


def test_a_changed_cell_is_named_with_both_values() -> None:
    after = snapshot(workers="id,node_id,tenant_id\nw1,n1,t2\nw2,n1,t1\n")

    assert compare_snapshots(snapshot(), after) == [
        "workers w1: tenant_id changed from 't1' to 't2'"
    ]


def test_a_removed_row_and_an_added_row_are_named() -> None:
    after = snapshot(workers="id,node_id,tenant_id\nw2,n1,t1\nw3,n1,t1\n")

    assert compare_snapshots(snapshot(), after) == [
        "workers w1: row removed",
        "workers w3: row added",
    ]


def test_a_changed_column_list_is_named() -> None:
    after = snapshot(
        workers="id,node_id,tenant_id,extra\nw1,n1,t1,x\nw2,n1,t1,x\n"
    )

    assert compare_snapshots(snapshot(), after) == [
        "workers: columns changed from ['id', 'node_id', 'tenant_id'] "
        "to ['id', 'node_id', 'tenant_id', 'extra']"
    ]


def test_a_table_missing_from_either_side_is_named() -> None:
    assert compare_snapshots(snapshot(), {"nodes": NODES}) == [
        "workers: missing from the after snapshot"
    ]
    assert compare_snapshots({"nodes": NODES}, snapshot()) == [
        "workers: missing from the before snapshot"
    ]


def test_a_quoted_comma_is_one_value_not_two() -> None:
    nodes = 'id,name\nn1,"a, b"\n'

    assert (
        compare_snapshots(snapshot(nodes=nodes), snapshot(nodes=nodes)) == []
    )
    assert compare_snapshots(
        snapshot(nodes=nodes),
        snapshot(nodes='id,name\nn1,"a, c"\n'),
    ) == ["nodes n1: name changed from 'a, b' to 'a, c'"]


def test_an_id_that_appears_twice_is_an_error_not_a_silent_overwrite() -> None:
    duplicated = snapshot(workers="id,node_id,tenant_id\nw1,n1,t1\nw1,n1,t2\n")

    with pytest.raises(ValueError, match="w1 appears twice"):
        compare_snapshots(snapshot(), duplicated)
