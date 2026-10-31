from __future__ import annotations

import pytest

from scripts import upgrade_rehearsal


def seeded() -> dict[str, str]:
    return {
        "public.nodes": "id,name\n1,swift-falcon\n",
        "public.workers": "id,node_id\n1,1\n",
        "public.jobs": "id,status\n1,SCHEDULED\n",
        "public.leases": "id,worker_id\n1,1\n",
    }


def test_a_fully_seeded_snapshot_has_no_problems() -> None:
    assert upgrade_rehearsal.empty_seed_tables(seeded()) == []


def test_a_table_with_only_a_header_is_reported_as_empty() -> None:
    snapshot = {**seeded(), "public.leases": "id,worker_id\n"}

    assert upgrade_rehearsal.empty_seed_tables(snapshot) == [
        "public.leases: has no rows"
    ]


def test_a_table_missing_from_the_snapshot_is_reported() -> None:
    snapshot = seeded()
    del snapshot["public.workers"]

    assert upgrade_rehearsal.empty_seed_tables(snapshot) == [
        "public.workers: not in the snapshot"
    ]


def test_problems_come_in_the_order_of_the_required_tables() -> None:
    snapshot = {**seeded(), "public.nodes": "id,name\n", "public.leases": "id\n"}
    del snapshot["public.workers"]

    assert upgrade_rehearsal.empty_seed_tables(snapshot) == [
        "public.nodes: has no rows",
        "public.workers: not in the snapshot",
        "public.leases: has no rows",
    ]


def test_tables_outside_the_required_list_may_be_empty() -> None:
    snapshot = {**seeded(), "public.events": "id,kind\n"}

    assert upgrade_rehearsal.empty_seed_tables(snapshot) == []


def test_the_required_tables_are_the_ones_the_seed_creates() -> None:
    assert upgrade_rehearsal.REQUIRED_SEED_TABLES == (
        "public.nodes",
        "public.workers",
        "public.jobs",
        "public.leases",
    )


def test_a_malformed_table_is_an_error_not_a_count() -> None:
    snapshot = {**seeded(), "public.nodes": "id,name\n1\n"}

    with pytest.raises(ValueError, match="public.nodes: line 2 has the wrong"):
        upgrade_rehearsal.empty_seed_tables(snapshot)
