"""
Extract the runnable setup blocks from README.md.

The README's setup commands are executed by CI instead of being
copied into a workflow, so the two cannot drift apart. Every bash
fence must carry a marker comment directly above it:

    <!-- ci:readme step=N name=NAME -->
    <!-- ci:readme skip name=NAME reason=REASON -->

A step marker means CI runs the block, in step order. A skip marker
records why a block is deliberately not run. A bash fence with no
marker is an error, so a new block cannot escape the check, and so
is a README with fewer than MIN_RUN_BLOCKS run blocks, so deleting
markers cannot make the job pass by running nothing.

Standard library only, because the first step runs before any
pip install. Block bodies are printed verbatim. Adapting them to a
checkout that already exists is the caller's job.

Usage:
    python scripts/readme_blocks.py            # validate, list steps
    python scripts/readme_blocks.py --step 2   # print one block
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

MIN_RUN_BLOCKS = 3

_TICKS = "`" * 3
_MARKER = re.compile(r"^<!-- ci:readme (?P<body>.+) -->$")
_BASH_FENCE = re.compile("^" + _TICKS + r"bash\s*$")

_Marker = tuple[str, "int | None", "str | None"]


class ReadmeBlockError(ValueError):
    """The README's setup blocks do not satisfy the marker contract."""


@dataclass(frozen=True)
class Block:
    name: str
    step: int | None
    reason: str | None
    body: str


def _parse_marker(body: str, lineno: int) -> _Marker:
    fields: dict[str, str] = {}
    skip = False
    for token in body.split():
        if token == "skip":
            skip = True
            continue
        key, separator, value = token.partition("=")
        if not separator or key not in {"step", "name", "reason"} or not value or key in fields:
            raise ReadmeBlockError(f"line {lineno}: bad marker token {token!r}")
        fields[key] = value
    if "name" not in fields:
        raise ReadmeBlockError(f"line {lineno}: marker has no name")
    name = fields["name"]
    if skip:
        if "step" in fields or "reason" not in fields:
            raise ReadmeBlockError(f"line {lineno}: a skip marker needs a reason and no step")
        return name, None, fields["reason"]
    if "step" not in fields or "reason" in fields:
        raise ReadmeBlockError(f"line {lineno}: a run marker needs step=N and no reason")
    if not fields["step"].isdigit() or int(fields["step"]) < 1:
        raise ReadmeBlockError(f"line {lineno}: step must be a positive integer")
    return name, int(fields["step"]), None


def _validate(blocks: list[Block]) -> None:
    names = [block.name for block in blocks]
    if len(set(names)) != len(names):
        raise ReadmeBlockError("block names must be unique")
    steps = sorted(block.step for block in blocks if block.step is not None)
    if len(steps) < MIN_RUN_BLOCKS:
        raise ReadmeBlockError(
            f"found {len(steps)} run blocks, expected at least {MIN_RUN_BLOCKS}"
        )
    if steps != list(range(1, len(steps) + 1)):
        raise ReadmeBlockError(f"steps must be 1..N with no gaps or repeats, got {steps}")


def parse_blocks(text: str) -> list[Block]:
    """Return every marked bash block in file order, or raise ReadmeBlockError."""
    blocks: list[Block] = []
    pending: _Marker | None = None
    pending_line = 0
    current: _Marker | None = None
    in_fence = False
    body_lines: list[str] = []

    for lineno, line in enumerate(text.splitlines(), start=1):
        if in_fence:
            if line.strip() == _TICKS:
                in_fence = False
                if current is not None:
                    name, step, reason = current
                    blocks.append(Block(name, step, reason, "\n".join(body_lines) + "\n"))
                    current = None
            elif current is not None:
                body_lines.append(line)
            continue

        if line.startswith(_TICKS):
            in_fence = True
            body_lines = []
            if _BASH_FENCE.match(line):
                if pending is None:
                    raise ReadmeBlockError(
                        f"line {lineno}: bash fence has no ci:readme marker directly above it"
                    )
                current, pending = pending, None
            elif pending is not None:
                raise ReadmeBlockError(
                    f"line {pending_line}: marker is not directly above a bash fence"
                )
            continue

        if pending is not None:
            raise ReadmeBlockError(
                f"line {pending_line}: marker is not directly above a bash fence"
            )
        match = _MARKER.match(line.strip())
        if match is not None:
            pending = _parse_marker(match.group("body"), lineno)
            pending_line = lineno

    if in_fence:
        raise ReadmeBlockError("a code fence is never closed")
    if pending is not None:
        raise ReadmeBlockError(f"line {pending_line}: marker is not directly above a bash fence")

    _validate(blocks)
    return blocks


def run_order(blocks: list[Block]) -> list[Block]:
    """The blocks CI runs, in step order, which is not always file order."""
    return sorted((block for block in blocks if block.step is not None), key=lambda b: b.step or 0)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract runnable README blocks.")
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    parser.add_argument("--step", type=int, help="print the body of this step")
    args = parser.parse_args(argv)

    try:
        blocks = parse_blocks(args.readme.read_text(encoding="utf-8"))
    except ReadmeBlockError as exc:
        print(f"README marker contract violated: {exc}", file=sys.stderr)
        return 1

    ordered = run_order(blocks)
    if args.step is None:
        for block in ordered:
            print(f"step {block.step}: {block.name}")
        return 0
    for block in ordered:
        if block.step == args.step:
            sys.stdout.write(block.body)
            return 0
    print(f"no run block has step {args.step}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
