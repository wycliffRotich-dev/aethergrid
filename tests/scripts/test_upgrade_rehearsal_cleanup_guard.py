from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from scripts import upgrade_rehearsal


@pytest.fixture
def no_docker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """
    A machine with git but no docker binary, and a temporary directory
    of its own so the test can see what the run left in it.
    """
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(upgrade_rehearsal, "_resolve", lambda ref: "0" * 40)
    monkeypatch.setattr(
        upgrade_rehearsal,
        "_export",
        lambda sha, destination: destination.mkdir(),
    )

    def run(
        command: Sequence[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "docker":
            raise FileNotFoundError("docker")
        return subprocess.CompletedProcess(list(command), 0, "", "")

    monkeypatch.setattr(upgrade_rehearsal, "_run", run)
    return tmp_path


def test_a_missing_docker_does_not_hide_the_error_of_the_run(
    no_docker: Path,
) -> None:
    with (
        pytest.raises(RuntimeError, match="the run failed"),
        upgrade_rehearsal.rehearsal_environment("old", "new"),
    ):
        raise RuntimeError("the run failed")

    assert list(no_docker.glob("upgrade-rehearsal-*")) == []


def test_a_good_run_whose_cleanup_cannot_be_checked_is_reported(
    no_docker: Path,
) -> None:
    with (
        pytest.raises(SystemExit, match="could not be listed"),
        upgrade_rehearsal.rehearsal_environment("old", "new"),
    ):
        pass

    assert list(no_docker.glob("upgrade-rehearsal-*")) == []
