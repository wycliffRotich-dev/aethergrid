"""
ADR 0095. The hardening function has to do what it says, not only be
called. The effect is shown in a subprocess, so the pytest process is
never made non-dumpable.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

MODULE = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "application"
    / "process_hardening.py"
)

_HARDEN_THEN_LET_A_CHILD_READ = r"""
import subprocess, sys
from app.application.process_hardening import make_unreadable_through_proc

if sys.argv[1] == "harden":
    make_unreadable_through_proc()

child = (
    "import os; "
    "print(b'leak-marker' in open(f'/proc/{os.getppid()}/environ','rb').read())"
)
done = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True)
print(done.stdout.strip() or "unreadable")
"""


def _what_the_child_could_read(mode: str) -> str:
    done = subprocess.run(
        [sys.executable, "-c", _HARDEN_THEN_LET_A_CHILD_READ, mode],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "SECRET": "leak-marker", "PYTHONPATH": "."},
        check=True,
    )

    return done.stdout.strip()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux only")
def test_without_hardening_a_child_reads_its_parents_environment() -> None:
    assert _what_the_child_could_read("plain") == "True"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux only")
def test_after_hardening_a_child_cannot_read_its_parents_environment() -> None:
    assert _what_the_child_could_read("harden") == "unreadable"


def test_the_module_uses_the_standard_library_only() -> None:
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(ast.parse(MODULE.read_text()))
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(ast.parse(MODULE.read_text()))
        if isinstance(node, ast.ImportFrom)
    }

    assert imported - set(sys.stdlib_module_names) - {"__future__"} == set()
