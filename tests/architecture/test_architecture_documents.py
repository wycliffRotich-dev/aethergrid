from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs" / "architecture"
README = DOCS / "README.md"

# A row of the contents table: "| 01-system-overview | High-level ... |".
ROW = re.compile(r"^\|\s*(\d{2}-[a-z0-9-]+)\s*\|")


def _listed() -> list[str]:
    return [
        match.group(1)
        for line in README.read_text(encoding="utf-8").splitlines()
        if (match := ROW.match(line))
    ]


def test_the_readme_lists_the_architecture_documents() -> None:
    assert _listed() != [], "no row of the contents table was recognized"


@pytest.mark.parametrize("name", _listed())
def test_a_listed_document_exists_and_has_content(name: str) -> None:
    path = DOCS / f"{name}.md"

    assert path.is_file(), f"{name}.md is listed in the README and does not exist"

    text = path.read_text(encoding="utf-8")

    assert text.strip() != "", f"{name}.md is empty, and the README lists it"
    assert any(line.startswith("# ") for line in text.splitlines()), (
        f"{name}.md has no title"
    )


def test_every_document_is_listed_in_the_readme() -> None:
    on_disk = {path.stem for path in DOCS.glob("*.md")} - {"README"}

    assert on_disk - set(_listed()) == set(), "a document is not in the README"
