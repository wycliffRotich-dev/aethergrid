from __future__ import annotations

import pytest

from app.domain.value_objects.api_key_scope import JOBS_EXECUTE
from scripts.issue_api_key import parse_args


def test_no_scope_flag_means_no_scopes() -> None:
    label, scopes = parse_args(["runner"])

    assert label == "runner"
    assert scopes == frozenset()


def test_scope_flag_grants_the_scope() -> None:
    _, scopes = parse_args(["runner", "--scope", JOBS_EXECUTE])

    assert scopes == frozenset({JOBS_EXECUTE})


def test_scope_flag_is_repeatable_and_deduplicated() -> None:
    _, scopes = parse_args(
        [
            "runner",
            "--scope",
            JOBS_EXECUTE,
            "--scope",
            JOBS_EXECUTE,
        ]
    )

    assert scopes == frozenset({JOBS_EXECUTE})


def test_unknown_scope_is_rejected_by_the_parser(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_args(["runner", "--scope", "job:execute"])

    assert excinfo.value.code == 2
    assert "job:execute" in capsys.readouterr().err


def test_missing_label_is_rejected() -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_args([])

    assert excinfo.value.code == 2
