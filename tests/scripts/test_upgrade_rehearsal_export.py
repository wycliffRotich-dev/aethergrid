from __future__ import annotations

import pytest

from scripts import upgrade_rehearsal
from scripts.upgrade_rehearsal import compare_snapshots


def test_a_null_that_becomes_an_empty_string_is_a_difference() -> None:
    before = {"items": "id,note\n1,\\N\n"}
    after = {"items": "id,note\n1,\n"}

    assert compare_snapshots(before, after) == [
        "items 1: note changed from '\\\\N' to ''"
    ]


def test_a_text_value_equal_to_the_null_marker_is_refused() -> None:
    snapshot = {"items": 'id,note\n1,"\\N"\n'}

    with pytest.raises(ValueError, match="items: .*null marker"):
        compare_snapshots(snapshot, snapshot)


def test_the_export_marks_null_apart_from_an_empty_string() -> None:
    sql = upgrade_rehearsal.copy_sql("public.items")

    assert sql.startswith("COPY public.items TO STDOUT")
    assert "FORMAT csv" in sql
    assert "HEADER" in sql
    assert "NULL '\\N'" in sql


def test_the_tables_are_listed_from_the_catalogue() -> None:
    sql = upgrade_rehearsal.TABLES_SQL

    assert "FROM pg_tables" in sql
    assert "format('%I.%I'" in sql
    assert "schemaname NOT IN ('pg_catalog', 'information_schema')" in sql
    assert "tablename <> 'schema_migrations'" in sql
