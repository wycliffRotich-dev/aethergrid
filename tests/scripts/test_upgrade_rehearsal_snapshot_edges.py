from __future__ import annotations

import pytest

from scripts.upgrade_rehearsal import compare_snapshots


def test_a_row_with_too_few_fields_is_an_error_not_a_blank_value() -> None:
    snapshot = {"items": "id,status\n1\n"}

    with pytest.raises(ValueError, match="items: line 2 has the wrong number"):
        compare_snapshots(snapshot, snapshot)


def test_a_row_with_too_many_fields_is_an_error() -> None:
    snapshot = {"items": "id,status\n1,paid,extra\n"}

    with pytest.raises(ValueError, match="items: line 2 has the wrong number"):
        compare_snapshots(snapshot, snapshot)
