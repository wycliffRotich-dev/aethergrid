from __future__ import annotations

import os
import time

import pytest

from app.application.services.job_execution_service import _read_launch_failure


def _status_pipe_holding(raw: bytes) -> int:
    """
    Return the read end of a status pipe whose write end already wrote
    raw and closed, the way a supervisor that ended leaves it.
    """
    read_end, write_end = os.pipe()
    os.write(write_end, raw)
    os.close(write_end)

    return read_end


def _read(raw: bytes) -> OSError | None:
    read_end = _status_pipe_holding(raw)

    try:
        return _read_launch_failure(read_end, time.monotonic() + 5.0)
    finally:
        os.close(read_end)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"errno": 2, "stre',
        b"not json at all",
        b'{"errno": 2}',
        b"[1, 2, 3]",
        b"\xff\xfe\xfd",
    ],
    ids=["cut_short", "not_json", "missing_keys", "wrong_shape", "not_text"],
)
def test_an_unreadable_launch_report_is_not_a_launch_failure(raw: bytes) -> None:
    assert _read(raw) is None


def test_a_complete_launch_report_is_read_as_the_launch_fault() -> None:
    raw = b'{"errno": 2, "strerror": "No such file or directory", "filename": "x"}'

    failure = _read(raw)

    assert isinstance(failure, FileNotFoundError)
    assert failure.filename == "x"
