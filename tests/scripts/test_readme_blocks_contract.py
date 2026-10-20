from __future__ import annotations

from pathlib import Path

import pytest

from scripts.readme_blocks import ReadmeBlockError, main, parse_blocks, run_order

FENCE = "`" * 3
REAL_README = Path(__file__).resolve().parents[2] / "README.md"


def _block(marker: str, body: str = "echo hi") -> str:
    return f"<!-- ci:readme {marker} -->\n{FENCE}bash\n{body}\n{FENCE}\n"


def _readme(*parts: str) -> str:
    return "\n".join(["# Title\n", *parts])


THREE = (
    _block("step=1 name=a"),
    _block("step=2 name=b"),
    _block("step=3 name=c"),
)


def test_blocks_run_in_step_order_not_file_order() -> None:
    text = _readme(
        _block("step=3 name=c"),
        _block("step=1 name=a"),
        _block("step=2 name=b"),
    )

    assert [b.name for b in run_order(parse_blocks(text))] == ["a", "b", "c"]


def test_skip_block_is_parsed_but_never_run() -> None:
    blocks = parse_blocks(_readme(*THREE, _block("skip name=front reason=dev-server")))

    skipped = [b for b in blocks if b.step is None]
    assert [b.name for b in skipped] == ["front"]
    assert skipped[0].reason == "dev-server"
    assert [b.name for b in run_order(blocks)] == ["a", "b", "c"]


def test_body_is_returned_verbatim() -> None:
    text = _readme(
        _block("step=1 name=a", "x=1\ny=$(date)"),
        THREE[1],
        THREE[2],
    )

    assert parse_blocks(text)[0].body == "x=1\ny=$(date)\n"


def test_unmarked_bash_fence_fails() -> None:
    text = _readme(*THREE, f"{FENCE}bash\nls\n{FENCE}\n")

    with pytest.raises(ReadmeBlockError, match="no ci:readme marker"):
        parse_blocks(text)


def test_non_bash_fence_needs_no_marker() -> None:
    text = _readme(*THREE, f"{FENCE}text\nhello\n{FENCE}\n")

    assert len(parse_blocks(text)) == 3


def test_fewer_than_three_run_blocks_fails() -> None:
    text = _readme(THREE[0], THREE[1], _block("skip name=c reason=why"))

    with pytest.raises(ReadmeBlockError, match="expected at least 3"):
        parse_blocks(text)


def test_readme_with_no_blocks_fails() -> None:
    with pytest.raises(ReadmeBlockError, match="expected at least 3"):
        parse_blocks("# Title\n\nno blocks here\n")


def test_duplicate_step_fails() -> None:
    text = _readme(THREE[0], THREE[1], _block("step=2 name=c"))

    with pytest.raises(ReadmeBlockError, match="no gaps or repeats"):
        parse_blocks(text)


def test_gap_in_steps_fails() -> None:
    text = _readme(THREE[0], THREE[1], _block("step=4 name=c"))

    with pytest.raises(ReadmeBlockError, match="no gaps or repeats"):
        parse_blocks(text)


def test_duplicate_name_fails() -> None:
    text = _readme(THREE[0], THREE[1], _block("step=3 name=a"))

    with pytest.raises(ReadmeBlockError, match="names must be unique"):
        parse_blocks(text)


def test_marker_with_a_gap_before_its_fence_fails() -> None:
    text = _readme(*THREE, "<!-- ci:readme step=4 name=d -->\n\nsome text\n")

    with pytest.raises(ReadmeBlockError, match="not directly above"):
        parse_blocks(text)


def test_marker_at_end_of_file_fails() -> None:
    text = _readme(*THREE, "<!-- ci:readme step=4 name=d -->")

    with pytest.raises(ReadmeBlockError, match="not directly above"):
        parse_blocks(text)


def test_unclosed_fence_fails() -> None:
    text = _readme(*THREE, f"<!-- ci:readme step=4 name=d -->\n{FENCE}bash\nls\n")

    with pytest.raises(ReadmeBlockError, match="never closed"):
        parse_blocks(text)


@pytest.mark.parametrize(
    "marker",
    [
        "step=1",
        "step=0 name=a",
        "step=x name=a",
        "skip name=a",
        "step=1 name=a reason=r",
        "step=1 name=a bogus",
        "step=1 name=a name=b",
        "skip step=1 name=a reason=r",
    ],
)
def test_malformed_marker_fails(marker: str) -> None:
    with pytest.raises(ReadmeBlockError):
        parse_blocks(_readme(_block(marker)))


def test_cli_prints_one_block_verbatim(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        _readme(THREE[0], _block("step=2 name=b", "echo second"), THREE[2]),
        encoding="utf-8",
    )

    assert main(["--readme", str(readme), "--step", "2"]) == 0
    assert capsys.readouterr().out == "echo second\n"


def test_cli_exits_nonzero_on_a_violation(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# no blocks\n", encoding="utf-8")

    assert main(["--readme", str(readme)]) == 1


def test_real_readme_satisfies_the_contract() -> None:
    blocks = parse_blocks(REAL_README.read_text(encoding="utf-8"))

    assert [b.name for b in run_order(blocks)] == ["first-run", "key", "tests"]
    assert [b.name for b in blocks if b.step is None] == ["frontend"]
