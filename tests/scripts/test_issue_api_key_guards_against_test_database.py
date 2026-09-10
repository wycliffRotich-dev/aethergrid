from __future__ import annotations

import pytest

from scripts.issue_api_key import _confirm_not_test_database


def test_refuses_database_url_containing_test() -> None:
    with pytest.raises(RuntimeError, match="looks like a test database"):
        _confirm_not_test_database(
            "postgresql://neuromesh:neuromesh@localhost:5433/neuromesh_test"
        )


def test_allows_database_url_without_test() -> None:
    _confirm_not_test_database(
        "postgresql://neuromesh:neuromesh@localhost:5433/neuromesh"
    )


def test_check_is_case_insensitive() -> None:
    with pytest.raises(RuntimeError, match="looks like a test database"):
        _confirm_not_test_database(
            "postgresql://neuromesh:neuromesh@localhost:5433/NeuroMesh_TEST"
        )
