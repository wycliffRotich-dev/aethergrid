"""
ADR 0095. A job's command must never start with the executor's own
environment. The supervisor is the only place a command is started, so
every subprocess launch in it must pass env explicitly.
"""

from __future__ import annotations

import ast
from pathlib import Path

SUPERVISOR = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "application"
    / "services"
    / "job_supervisor.py"
)

_LAUNCHERS = {"Popen", "run", "call", "check_call", "check_output"}


def _launch_name(call: ast.Call) -> str | None:
    func = call.func

    if isinstance(func, ast.Name) and func.id == "Popen":
        return func.id

    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
        and func.attr in _LAUNCHERS
    ):
        return func.attr

    return None


def launches_without_env(source: str) -> list[int]:
    """Line numbers of subprocess launches that do not pass env."""
    lines: list[int] = []

    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or _launch_name(node) is None:
            continue

        if not any(keyword.arg == "env" for keyword in node.keywords):
            lines.append(node.lineno)

    return sorted(lines)


def test_every_launch_in_the_supervisor_passes_an_environment() -> None:
    assert launches_without_env(SUPERVISOR.read_text()) == []


def test_the_check_flags_a_launch_that_inherits_the_environment() -> None:
    source = "import subprocess\nsubprocess.Popen(['x'])\n"

    assert launches_without_env(source) == [2]


def test_the_check_accepts_a_launch_that_passes_an_environment() -> None:
    source = "import subprocess\nsubprocess.Popen(['x'], env={})\n"

    assert launches_without_env(source) == []
