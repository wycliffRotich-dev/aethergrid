from __future__ import annotations

from pathlib import Path

import pytest

from app.presentation.dependencies import _build_repositories

# ADR 0026: a script that issues real credentials must never succeed
# against a throwaway in-memory store because a variable was forgotten.


def test_an_unset_backend_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEUROMESH_STORAGE_BACKEND", raising=False)

    with pytest.raises(RuntimeError, match="is not set"):
        _build_repositories()


@pytest.mark.parametrize("value", ["", "mongo", "postgresql", " memory"])
def test_an_unrecognized_backend_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("NEUROMESH_STORAGE_BACKEND", value)

    with pytest.raises(RuntimeError, match="Unrecognized"):
        _build_repositories()


def test_the_memory_backend_is_accepted_when_named_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEUROMESH_STORAGE_BACKEND", "MEMORY")

    repositories = _build_repositories()

    assert repositories[-1] is None


def test_the_sqlite_backend_is_accepted_when_named_explicitly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NEUROMESH_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("NEUROMESH_DB_PATH", str(tmp_path / "probe.db"))

    repositories = _build_repositories()

    assert repositories[-1] is None
