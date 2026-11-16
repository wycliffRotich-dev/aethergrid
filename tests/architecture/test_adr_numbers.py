from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

ADRS = Path(__file__).resolve().parents[2] / "docs" / "adr"

# NNNN-kebab-case-title.md
FILENAME = re.compile(r"^(\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
# "# ADR NNNN: Title"
TITLE = re.compile(r"^# ADR (\d{4}): \S")


def find_adr_problems(files: dict[str, str]) -> list[str]:
    """Return one message per violation of the ADR numbering rules.

    The rules: every filename is NNNN-kebab-case-title.md, the first line
    of the file is "# ADR NNNN: Title" with the same number as the
    filename, no two files share a number, and no line contains an em
    dash. Gaps are allowed, because a number can be reserved by an open
    pull request.
    """
    problems: list[str] = []
    by_number: dict[str, list[str]] = defaultdict(list)

    for name in sorted(files):
        for line_number, text_line in enumerate(files[name].splitlines(), start=1):
            if "\u2014" in text_line:
                problems.append(f"{name}: line {line_number} contains an em dash")

        match = FILENAME.match(name)

        if match is None:
            problems.append(f"{name}: filename must be NNNN-kebab-case-title.md")
            continue

        number = match.group(1)
        by_number[number].append(name)

        lines = files[name].splitlines()
        title = TITLE.match(lines[0]) if lines else None

        if title is None:
            problems.append(f"{name}: first line must read: # ADR {number}: Title")
        elif title.group(1) != number:
            problems.append(
                f"{name}: the title says ADR {title.group(1)} "
                f"but the filename says {number}"
            )

    for number, names in sorted(by_number.items()):
        if len(names) > 1:
            problems.append(
                f"ADR number {number} is used by {len(names)} files: "
                + ", ".join(names)
            )

    return problems


def _adr(number: str, title: str = "Some Decision") -> str:
    return f"# ADR {number}: {title}\n\n## Status\n\nAccepted\n"


def test_a_consistent_set_with_gaps_has_no_problems() -> None:
    files = {
        "0001-first-decision.md": _adr("0001"),
        "0004-fourth-decision.md": _adr("0004"),
    }

    assert find_adr_problems(files) == []


def test_two_files_sharing_a_number_are_flagged() -> None:
    files = {
        "0097-create-a-public-read-role.md": _adr("0097"),
        "0097-make-node-capacity-accounting-atomic.md": _adr("0097"),
    }

    problems = find_adr_problems(files)

    assert len(problems) == 1
    assert "0097" in problems[0]
    assert "0097-create-a-public-read-role.md" in problems[0]
    assert "0097-make-node-capacity-accounting-atomic.md" in problems[0]


def test_a_malformed_filename_is_flagged() -> None:
    names = (
        "97-short-number.md",
        "0102_underscores.md",
        "0102-Upper-Case.md",
        "0102-title.txt",
    )
    for name in names:
        problems = find_adr_problems({name: _adr("0102")})

        assert any(name in problem for problem in problems), name


def test_a_title_number_that_differs_from_the_filename_is_flagged() -> None:
    files = {"0102-a-decision.md": _adr("0096")}

    problems = find_adr_problems(files)

    assert len(problems) == 1
    assert "0102-a-decision.md" in problems[0]
    assert "0096" in problems[0]


def test_a_missing_title_is_flagged() -> None:
    files = {"0102-a-decision.md": "No heading here.\n"}

    problems = find_adr_problems(files)

    assert len(problems) == 1
    assert "0102-a-decision.md" in problems[0]


def test_the_adr_directory_has_no_problems() -> None:
    files = {
        path.name: path.read_text(encoding="utf-8")
        for path in ADRS.iterdir()
        if path.is_file()
    }

    assert files != {}, "docs/adr has no files"
    assert find_adr_problems(files) == []


def test_an_em_dash_in_the_text_is_flagged_with_its_line() -> None:
    files = {"0102-a-decision.md": _adr("0102") + "A cost \u2014 a benefit.\n"}

    problems = find_adr_problems(files)

    assert len(problems) == 1
    assert "0102-a-decision.md" in problems[0]
    assert "line 6" in problems[0]


def test_a_plain_hyphen_in_the_text_is_not_flagged() -> None:
    files = {"0102-a-decision.md": _adr("0102") + "A cost - a benefit.\n"}

    assert find_adr_problems(files) == []
