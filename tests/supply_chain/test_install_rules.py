"""
Supply chain rules for how CI and the image install Python packages.

Every pip install must either verify hashes against a lock or add nothing
(--no-deps). A bare "pip install ." or "pip install -e .[dev]" resolves
versions fresh, so a passing run says nothing about what the image holds.
The base image must be named by digest, and the image keeps no compiler,
because every locked package ships a wheel.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))
DOCKERFILE = ROOT / "Dockerfile"

CHAIN = re.compile(r"&&|;|\|")
FROM = re.compile(
    r"^FROM\s+(?:--\S+\s+)?(?P<image>\S+)(?:\s+AS\s+(?P<alias>\S+))?",
    re.M | re.I,
)
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
COMPILERS = re.compile(r"\b(gcc|g\+\+|build-essential|clang)\b")


def unsafe_installs(text: str) -> list[str]:
    joined = text.replace("\\\n", " ")
    bad: list[str] = []

    for line in joined.splitlines():
        for part in CHAIN.split(line):
            if "pip install" not in part:
                continue
            if "--require-hashes" in part or "--no-deps" in part:
                continue
            bad.append(part.strip())

    return bad


def unpinned_bases(text: str) -> list[str]:
    stages: set[str] = set()
    bad: list[str] = []

    for match in FROM.finditer(text):
        image = match.group("image")

        if image not in stages and not DIGEST.search(image):
            bad.append(image)

        if match.group("alias"):
            stages.add(match.group("alias"))

    return bad


def test_the_scan_finds_its_files() -> None:
    assert WORKFLOWS, "no workflow files found"
    assert DOCKERFILE.is_file(), "no Dockerfile found"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_a_workflow_installs_only_from_a_lock(path: Path) -> None:
    assert unsafe_installs(path.read_text(encoding="utf-8")) == []


def test_the_image_installs_only_from_a_lock() -> None:
    assert unsafe_installs(DOCKERFILE.read_text(encoding="utf-8")) == []


def test_the_image_base_is_pinned_by_digest() -> None:
    assert unpinned_bases(DOCKERFILE.read_text(encoding="utf-8")) == []


def test_the_image_holds_no_compiler() -> None:
    assert COMPILERS.findall(DOCKERFILE.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "source",
    [
        'pip install -e ".[dev]"',
        "python -m pip install --upgrade pip",
        "RUN pip install --no-cache-dir .",
        "pip install --require-hashes -r a.lock && pip install requests",
    ],
)
def test_an_install_without_a_lock_is_flagged(source: str) -> None:
    assert len(unsafe_installs(source)) == 1


def test_a_continued_line_is_read_as_one_command() -> None:
    source = "RUN pip install --upgrade pip \\\n    && pip install ."

    assert len(unsafe_installs(source)) == 2


def test_a_hashed_install_and_a_no_deps_install_pass() -> None:
    source = (
        "python -m pip install --require-hashes -r requirements.lock\n"
        "python -m pip install --no-deps --no-build-isolation -e .\n"
    )

    assert unsafe_installs(source) == []


@pytest.mark.parametrize(
    "source",
    ["FROM python:3.11-slim AS base", "FROM python:3.11-slim"],
)
def test_a_base_without_a_digest_is_flagged(source: str) -> None:
    assert unpinned_bases(source) == ["python:3.11-slim"]


def test_a_digest_and_a_reference_to_an_earlier_stage_pass() -> None:
    source = (
        "FROM python:3.11-slim@sha256:" + "a" * 64 + " AS base\n"
        "FROM base AS final\n"
    )

    assert unpinned_bases(source) == []
