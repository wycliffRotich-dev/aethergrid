from __future__ import annotations

import pytest

from app.domain.entities.api_key import ApiKey
from app.domain.exceptions.unknown_api_key_scope_error import (
    UnknownApiKeyScopeError,
)
from app.domain.value_objects.api_key_scope import (
    JOBS_EXECUTE,
    KNOWN_SCOPES,
    validate_scopes,
)


def test_jobs_execute_is_in_the_vocabulary() -> None:
    assert JOBS_EXECUTE == "jobs:execute"
    assert JOBS_EXECUTE in KNOWN_SCOPES


def test_validate_scopes_accepts_empty() -> None:
    assert validate_scopes(frozenset()) == frozenset()


def test_validate_scopes_accepts_a_list_of_known() -> None:
    assert validate_scopes([JOBS_EXECUTE]) == frozenset(
        {JOBS_EXECUTE}
    )


def test_validate_scopes_rejects_a_typo() -> None:
    with pytest.raises(UnknownApiKeyScopeError) as excinfo:
        validate_scopes({"job:execute"})

    assert excinfo.value.scope == "job:execute"
    assert "jobs:execute" in str(excinfo.value)


def test_validate_scopes_rejects_known_mixed_with_unknown() -> None:
    with pytest.raises(UnknownApiKeyScopeError):
        validate_scopes({JOBS_EXECUTE, "jobs:everything"})


def test_validate_scopes_rejects_a_bare_string() -> None:
    with pytest.raises(TypeError):
        validate_scopes("jobs:execute")  # type: ignore[arg-type]


def test_issue_rejects_an_unknown_scope() -> None:
    with pytest.raises(UnknownApiKeyScopeError):
        ApiKey.issue(
            label="runner",
            scopes=frozenset({"job:execute"}),
        )
