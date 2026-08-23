from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.presentation.schemas.create_job_request import (
    CreateJobRequest,
)


def test_create_job_request_allows_missing_command() -> None:
    """
    command is optional. Omitting it entirely must still
    produce a valid request, matching every job created
    before ADR 0028 existed.
    """
    request = CreateJobRequest(
        cpu_cores=1,
        memory_mib=512,
        vram_mib=0,
    )

    assert request.command is None


def test_create_job_request_accepts_valid_command() -> None:
    request = CreateJobRequest(
        cpu_cores=1,
        memory_mib=512,
        vram_mib=0,
        command=["python", "train.py", "--epochs", "5"],
    )

    assert request.command == [
        "python",
        "train.py",
        "--epochs",
        "5",
    ]


def test_create_job_request_rejects_empty_command_list() -> None:
    """
    An empty command list would reach JobExecutionService's
    subprocess.Popen call with no argv at all, failing
    late and unhelpfully deep in a worker's execution loop
    instead of at request time. See ADR 0028.
    """
    with pytest.raises(ValidationError):
        CreateJobRequest(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
            command=[],
        )


def test_create_job_request_rejects_blank_command_argument() -> None:
    with pytest.raises(ValidationError):
        CreateJobRequest(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
            command=["python", "  ", "train.py"],
        )
