"""
Every job in every workflow must set timeout-minutes. Without it a job
that stalls runs for up to six hours. One test job once ran 23 minutes
against a normal 2 and nothing stopped it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))

JOBS_HEADER = re.compile(r"^jobs:\s*$", re.M)
JOB_NAME = re.compile(r"^  (?P<name>[A-Za-z0-9_-]+):\s*$", re.M)
TIMEOUT = re.compile(r"^    timeout-minutes:\s*\d+\s*$", re.M)


def jobs_without_a_timeout(text: str) -> list[str]:
    header = JOBS_HEADER.search(text)

    if header is None:
        return []

    body = text[header.end():]
    starts = list(JOB_NAME.finditer(body))
    missing: list[str] = []

    for i, start in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(body)

        if not TIMEOUT.search(body[start.end():end]):
            missing.append(start.group("name"))

    return missing


def test_the_scan_finds_the_workflow_files() -> None:
    assert WORKFLOWS, "no workflow files found"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_job_sets_a_timeout(path: Path) -> None:
    assert jobs_without_a_timeout(path.read_text(encoding="utf-8")) == []


def test_a_job_without_a_timeout_is_flagged() -> None:
    source = "jobs:\n  build:\n    runs-on: ubuntu-24.04\n    steps: []\n"

    assert jobs_without_a_timeout(source) == ["build"]


def test_only_the_job_that_lacks_one_is_flagged() -> None:
    source = (
        "jobs:\n"
        "  a:\n    timeout-minutes: 10\n    steps: []\n"
        "  b:\n    runs-on: x\n    steps: []\n"
    )

    assert jobs_without_a_timeout(source) == ["b"]


def test_a_timeout_in_a_step_does_not_count_for_the_job() -> None:
    source = "jobs:\n  a:\n    steps:\n      - run: x\n        timeout-minutes: 5\n"

    assert jobs_without_a_timeout(source) == ["a"]


def test_a_job_with_a_timeout_passes() -> None:
    source = "jobs:\n  a:\n    runs-on: x\n    timeout-minutes: 15\n    steps: []\n"

    assert jobs_without_a_timeout(source) == []
