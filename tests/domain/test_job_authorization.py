from __future__ import annotations

import pytest

from app.domain.exceptions.scope_denied_error import (
    ScopeDeniedError,
)
from app.domain.services.job_authorization import (
    authorize_job_creation,
)
from app.domain.value_objects.api_key_scope import JOBS_EXECUTE

REAL_COMMAND = ["python", "train.py"]

# (scopes held, command supplied, allowed)
CASES = [
    pytest.param(
        frozenset(), None, True, id="unscoped-no-command"
    ),
    pytest.param(
        frozenset(), [], False, id="unscoped-empty-command"
    ),
    pytest.param(
        frozenset(),
        REAL_COMMAND,
        False,
        id="unscoped-real-command",
    ),
    pytest.param(
        frozenset({JOBS_EXECUTE}),
        None,
        True,
        id="scoped-no-command",
    ),
    pytest.param(
        frozenset({JOBS_EXECUTE}),
        [],
        True,
        id="scoped-empty-command",
    ),
    pytest.param(
        frozenset({JOBS_EXECUTE}),
        REAL_COMMAND,
        True,
        id="scoped-real-command",
    ),
    pytest.param(
        frozenset({"jobs:other"}),
        REAL_COMMAND,
        False,
        id="unrelated-scope-real-command",
    ),
]


@pytest.mark.parametrize(("scopes", "command", "allowed"), CASES)
def test_authorize_job_creation_truth_table(
    scopes: frozenset[str],
    command: list[str] | None,
    allowed: bool,
) -> None:
    if allowed:
        authorize_job_creation(scopes, command)
        return

    with pytest.raises(ScopeDeniedError) as excinfo:
        authorize_job_creation(scopes, command)

    assert excinfo.value.scope == JOBS_EXECUTE
    assert "jobs:execute" in str(excinfo.value)
