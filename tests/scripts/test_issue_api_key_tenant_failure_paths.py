from __future__ import annotations

from typing import NoReturn

import pytest

from app.domain.exceptions.tenant_already_exists_error import (
    TenantAlreadyExistsError,
)
from app.presentation import dependencies
from scripts.issue_api_key import main

# ADR 0090: a name taken between the lookup and the save reaches the
# script as the repository's TenantAlreadyExistsError. The memory
# subprocess cannot produce that race, so main runs in-process with a
# resolver that loses it.


class RacedResolver:
    """Reports a name another operator took after our lookup."""

    def execute(
        self,
        name: str,
        *,
        create_if_missing: bool = False,
    ) -> NoReturn:
        raise TenantAlreadyExistsError(
            f"tenant name '{name}' is already held by a different tenant"
        )


def _fail_if_a_key_is_issued() -> NoReturn:
    raise AssertionError("a key was issued after the tenant failed")


def test_a_name_taken_in_the_meantime_is_an_error_and_issues_no_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("NEUROMESH_DATABASE_URL", raising=False)
    monkeypatch.setattr(
        dependencies,
        "get_resolve_tenant_service",
        RacedResolver,
    )
    monkeypatch.setattr(
        dependencies,
        "get_create_api_key_service",
        _fail_if_a_key_is_issued,
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["runner", "--tenant", "acme", "--create-tenant"])

    message = str(excinfo.value.code)
    assert message.startswith("error: ")
    assert "acme" in message
    assert capsys.readouterr().out == ""
