from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.application.services.job_execution_service import (
    JobExecutionResult,
    JobExecutionService,
)


def _command_that_cannot_start(kind: str, directory: Path) -> list[str]:
    if kind == "missing":
        return [str(directory / "no-such-binary")]

    plain_file = directory / "plain-file"
    plain_file.write_text("not a program\n")
    plain_file.chmod(0o644)

    if kind == "not_executable":
        return [str(plain_file)]

    return [str(plain_file / "inside")]


def _execute(command: list[str]) -> JobExecutionResult:
    return JobExecutionService().execute(
        command=command,
        timeout=timedelta(seconds=5),
    )


@pytest.mark.parametrize(
    "kind",
    ["missing", "not_executable", "through_a_file"],
)
def test_a_command_that_cannot_start_is_a_failed_job(
    tmp_path: Path, kind: str
) -> None:
    result = _execute(_command_that_cannot_start(kind, tmp_path))

    assert result.succeeded is False
    assert result.exit_code is None
    assert result.timed_out is False
    assert result.cancelled is False
    assert result.lease_lost is False


def test_the_reason_a_command_cannot_start_is_named(
    tmp_path: Path,
) -> None:
    command = _command_that_cannot_start("missing", tmp_path)

    result = _execute(command)

    assert command[0] in result.stderr
