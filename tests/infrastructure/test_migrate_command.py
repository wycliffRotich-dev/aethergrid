from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.infrastructure.database_credentials import PASSWORD_FILE_ENV, URL_ENV
from app.infrastructure.migrations import cli
from app.infrastructure.migrations.cli import main

ROOT = Path(__file__).resolve().parents[2]
UNUSED_URL = "postgresql://u@db.invalid:5432/app"


@pytest.fixture
def scratch(
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[psycopg.Connection]:
    """
    One throwaway schema. The command opens its own connection, so the
    schema reaches it through libpq's PGOPTIONS, which in-process and
    subprocess runs both inherit.
    """
    schema = f"cli_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(test_database_url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.execute(f'SET search_path TO "{schema}"')
        monkeypatch.setenv("PGOPTIONS", f"-c search_path={schema}")
        try:
            yield conn
        finally:
            conn.execute("SET search_path TO public")
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


def _password_file(tmp_path: Path, content: str | None) -> Path:
    path = tmp_path / "password"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    return path


def test_applies_every_migration_to_an_empty_database(
    scratch: psycopg.Connection,
    test_database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main({URL_ENV: test_database_url}) == 0

    output = capsys.readouterr().out
    assert "applied 0001_baseline.sql" in output
    assert "applied 0002_give_events_a_tenant.sql" in output
    assert scratch.execute("SELECT version FROM schema_migrations").fetchall() == [
        (1,),
        (2,),
    ]
    tenants = scratch.execute("SELECT id::text FROM tenants").fetchall()
    assert tenants == [(str(DEFAULT_TENANT_ID),)]


def test_a_second_run_has_nothing_to_apply(
    scratch: psycopg.Connection,
    test_database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main({URL_ENV: test_database_url})
    capsys.readouterr()

    assert main({URL_ENV: test_database_url}) == 0

    assert "nothing to apply" in capsys.readouterr().out


def test_a_missing_url_is_a_startup_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main({}) == 2

    assert URL_ENV in capsys.readouterr().err


def test_the_password_file_reaches_the_connection_and_not_the_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_apply(conninfo: str, migrations: Any, **kwargs: Any) -> list[int]:
        calls.append((conninfo, kwargs))
        return []

    monkeypatch.setattr(cli, "apply_migrations", fake_apply)
    env = {
        URL_ENV: UNUSED_URL,
        PASSWORD_FILE_ENV: str(_password_file(tmp_path, "s3cret\n")),
    }

    assert main(env) == 0

    assert len(calls) == 1
    conninfo, kwargs = calls[0]
    assert kwargs["connect_kwargs"]["password"] == "s3cret"
    assert "s3cret" not in conninfo
    captured = capsys.readouterr()
    assert "s3cret" not in captured.out + captured.err


def test_a_password_in_the_url_and_in_the_file_is_a_startup_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = {
        URL_ENV: "postgresql://u:p@db.invalid:5432/app",
        PASSWORD_FILE_ENV: str(_password_file(tmp_path, "x\n")),
    }

    assert main(env) == 2

    assert PASSWORD_FILE_ENV in capsys.readouterr().err


@pytest.mark.parametrize("content", [None, ""])
def test_an_unreadable_or_empty_password_file_is_a_startup_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    content: str | None,
) -> None:
    env = {URL_ENV: UNUSED_URL, PASSWORD_FILE_ENV: str(_password_file(tmp_path, content))}

    assert main(env) == 2

    assert PASSWORD_FILE_ENV in capsys.readouterr().err


def test_a_failing_migration_exits_1_and_names_the_file(
    scratch: psycopg.Connection,
    test_database_url: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "0001_boom.sql").write_text("SELECT 1/0;\n", encoding="utf-8")

    assert main({URL_ENV: test_database_url}, directory=tmp_path) == 1

    assert "0001_boom.sql" in capsys.readouterr().err


def test_a_connection_failure_exits_1_and_never_prints_the_password(
    capsys: pytest.CaptureFixture[str],
) -> None:
    url = "postgresql://u:s3cret@127.0.0.1:1/app?connect_timeout=2"

    assert main({URL_ENV: url}) == 1

    captured = capsys.readouterr()
    assert "s3cret" not in captured.out + captured.err


def test_a_missing_migrations_directory_is_a_startup_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main({URL_ENV: UNUSED_URL}, directory=tmp_path / "missing") == 2

    assert "does not exist" in capsys.readouterr().err


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "app.infrastructure.migrations"],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
        timeout=60,
    )


def test_the_module_entry_point_applies_migrations(
    scratch: psycopg.Connection,
    test_database_url: str,
) -> None:
    result = _run({**os.environ, URL_ENV: test_database_url})

    assert result.returncode == 0, result.stderr
    assert "applied 0001_baseline.sql" in result.stdout


def test_the_module_entry_point_exits_2_without_a_database_url() -> None:
    result = _run({k: v for k, v in os.environ.items() if k != URL_ENV})

    assert result.returncode == 2
    assert URL_ENV in result.stderr
