from __future__ import annotations

import dataclasses
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.domain.value_objects.api_key_scope import JOBS_EXECUTE
from scripts.issue_api_key import parse_args

# ADR 0090: --tenant and --create-tenant, and a usage text that needs no
# storage backend. The script runs as a real subprocess on the memory
# backend, so the tests see what an operator sees.

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "issue_api_key.py"
UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
DEFAULT_ID = "00000000-0000-0000-0000-000000000001"


def run_script(
    args: list[str],
    *,
    backend: str | None = "memory",
) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("NEUROMESH_")
    }
    if backend is not None:
        env["NEUROMESH_STORAGE_BACKEND"] = backend
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
        timeout=60,
        check=False,
    )


def test_no_tenant_option_means_the_default_tenant() -> None:
    args = parse_args(["runner"])

    assert args.label == "runner"
    assert args.scopes == frozenset()
    assert args.tenant_name is None
    assert args.create_tenant is False


def test_tenant_option_names_the_tenant() -> None:
    args = parse_args(["runner", "--tenant", "acme"])

    assert args.tenant_name == "acme"
    assert args.create_tenant is False


def test_create_tenant_option_is_parsed_with_a_tenant() -> None:
    args = parse_args(["runner", "--tenant", "acme", "--create-tenant"])

    assert args.tenant_name == "acme"
    assert args.create_tenant is True


def test_create_tenant_without_a_tenant_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_args(["runner", "--create-tenant"])

    assert excinfo.value.code == 2
    assert "--create-tenant requires --tenant" in capsys.readouterr().err


def test_scopes_and_tenant_combine() -> None:
    args = parse_args(
        ["runner", "--scope", JOBS_EXECUTE, "--tenant", "acme"]
    )

    assert args.scopes == frozenset({JOBS_EXECUTE})
    assert args.tenant_name == "acme"


def test_the_parsed_arguments_are_frozen() -> None:
    args = parse_args(["runner"])

    with pytest.raises(dataclasses.FrozenInstanceError):
        args.label = "other"  # type: ignore[misc]


def test_help_prints_without_a_storage_backend() -> None:
    result = run_script(["--help"], backend=None)

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("usage:")
    assert "--tenant" in result.stdout
    assert "--create-tenant" in result.stdout


def test_a_key_for_the_default_tenant_prints_what_it_always_did() -> None:
    result = run_script(["runner"])

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "Issued API key for 'runner':"
    assert lines[1] != "" and len(lines[1].split()) == 1
    assert lines[2] == ""
    assert lines[3] == "Scopes: none"
    assert result.stderr == ""


def test_an_unknown_tenant_is_refused_without_a_traceback() -> None:
    result = run_script(["runner", "--tenant", "acme"])

    assert result.returncode == 1
    assert result.stdout == ""
    assert "acme" in result.stderr
    assert "--create-tenant" in result.stderr
    assert "Traceback" not in result.stderr


def test_create_tenant_issues_the_key_and_says_so_on_stderr() -> None:
    result = run_script(["runner", "--tenant", "acme", "--create-tenant"])

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "Issued API key for 'runner':"
    assert re.fullmatch(
        rf"Created tenant 'acme' \({UUID}\)\.",
        result.stderr.strip(),
    )
    assert lines[1] not in result.stderr


def test_an_existing_tenant_is_used_and_not_created() -> None:
    result = run_script(["runner", "--tenant", "default"])

    assert result.returncode == 0, result.stderr
    assert result.stderr.strip() == (
        f"Using tenant 'default' ({DEFAULT_ID})."
    )


def test_a_blank_tenant_name_is_refused_without_a_traceback() -> None:
    result = run_script(["runner", "--tenant", "   "])

    assert result.returncode == 1
    assert result.stdout == ""
    assert "tenant name" in result.stderr
    assert "Traceback" not in result.stderr
