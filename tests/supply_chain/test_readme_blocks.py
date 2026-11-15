"""
The README setup blocks are run on a clean runner by
readme-clean-clone.yml (ADR 0076), so the installs in them are installs
in CI. The workflow file names no pip install itself, which is why the
workflow scan cannot see them. This reads the blocks the way the
workflow does and applies the same install rule.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.supply_chain.test_install_rules import unsafe_installs

ROOT = Path(__file__).resolve().parents[2]
STEPS = (1, 2, 3)


def _block(step: int) -> str:
    done = subprocess.run(
        [sys.executable, "scripts/readme_blocks.py", "--step", str(step)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    return done.stdout


@pytest.mark.parametrize("step", STEPS)
def test_a_readme_block_is_not_empty(step: int) -> None:
    assert _block(step).strip()


@pytest.mark.parametrize("step", STEPS)
def test_a_readme_block_installs_only_from_a_lock(step: int) -> None:
    assert unsafe_installs(_block(step)) == []
