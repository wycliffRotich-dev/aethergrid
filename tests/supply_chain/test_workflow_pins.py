"""
Supply chain rules for the CI workflows.

A "uses:" line that names a tag can be re-pointed by whoever owns the
action, and some of these actions receive a secret. Each one must name a
full commit SHA instead. Local actions are the only exception.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))

USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<ref>\S+)", re.M)
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def unpinned(text: str) -> list[str]:
    found: list[str] = []

    for match in USES.finditer(text):
        ref = match.group("ref")

        if ref.startswith("./"):
            continue

        if not PINNED.match(ref):
            found.append(ref)

    return found


def test_the_scan_finds_the_workflow_files() -> None:
    assert WORKFLOWS, "no workflow files found, so the scan below would pass on nothing"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_commit(path: Path) -> None:
    assert unpinned(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "line",
    [
        "      - uses: actions/checkout@v7",
        "        uses: actions/checkout@main",
        "        uses: actions/checkout@" + "a" * 39,
        "        uses: owner/repo@" + "G" * 40,
        "        uses: owner/repo@" + "a" * 40 + "# v7",
        "        uses: owner/repo",
    ],
)
def test_a_mutable_reference_is_flagged(line: str) -> None:
    assert len(unpinned(line)) == 1


def test_a_commit_and_a_local_action_pass() -> None:
    source = (
        "        uses: actions/checkout@" + "a" * 40 + " # v7\n"
        "        uses: ./.github/actions/local\n"
    )

    assert unpinned(source) == []
