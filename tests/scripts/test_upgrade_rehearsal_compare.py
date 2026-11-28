from __future__ import annotations

import pytest

from scripts import upgrade_rehearsal
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


def test_a_table_missing_from_the_after_snapshot_is_named() -> None:
    assert compare_snapshots(snapshot(), {"nodes": NODES}) == [
        "workers: missing from the after snapshot"
    ]


def test_an_empty_table_created_by_the_upgrade_is_not_a_difference() -> None:
    after = {**snapshot(), "public.lease_reclaims": "id,tenant_id\n"}

    assert compare_snapshots(snapshot(), after) == []


def test_a_created_table_with_rows_is_named_with_its_row_count() -> None:
    after = {
        **snapshot(),
        "public.lease_refusals": "id,tenant_id\nr1,t1\n",
        "public.lease_reclaims": "id,tenant_id\nc1,t1\nc2,t1\n",
        "public.public_demo_scope": "tenant_id\n",
    }

    assert compare_snapshots(snapshot(), after) == [
        "public.lease_reclaims: created by the upgrade, rows: 2",
        "public.lease_refusals: created by the upgrade, rows: 1",
    ]


def test_a_created_table_with_no_header_is_an_error() -> None:
    after = {**snapshot(), "public.lease_reclaims": ""}

    with pytest.raises(ValueError, match="lease_reclaims: the export has no"):
        compare_snapshots(snapshot(), after)


def test_a_created_table_with_a_repeated_id_is_an_error() -> None:
    reclaims = "id,tenant_id\nc1,t1\nc1,t2\n"
    after = {**snapshot(), "public.lease_reclaims": reclaims}

    with pytest.raises(ValueError, match="c1 appears twice"):
        compare_snapshots(snapshot(), after)


def test_a_dropped_table_is_still_named_when_another_is_created() -> None:
    after = {"nodes": NODES, "public.lease_reclaims": "id,tenant_id\n"}

    assert compare_snapshots(snapshot(), after) == [
        "workers: missing from the after snapshot"
    ]


def test_the_tables_created_by_the_upgrade_are_listed_in_order() -> None:
    after = {
        **snapshot(),
        "public.lease_refusals": "id,tenant_id\n",
        "public.lease_reclaims": "id,tenant_id\nc1,t1\n",
    }

    assert upgrade_rehearsal.created_tables(snapshot(), after) == [
        "public.lease_reclaims",
        "public.lease_refusals",
    ]


def test_no_created_table_gives_an_empty_list() -> None:
    assert upgrade_rehearsal.created_tables(snapshot(), snapshot()) == []


def test_a_dropped_table_is_not_listed_as_created() -> None:
    after = {"nodes": NODES}

    assert upgrade_rehearsal.created_tables(snapshot(), after) == []


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
