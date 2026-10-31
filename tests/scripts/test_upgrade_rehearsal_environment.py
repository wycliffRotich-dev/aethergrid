from __future__ import annotations

import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

import scripts.upgrade_rehearsal as rehearsal
from scripts.upgrade_rehearsal import REPO_ROOT, render_override

OVERRIDE = render_override(
    secret_file=Path("/tmp/run/postgres_password"),
    db_port=41001,
    api_port=41002,
    tag_prefix="rehearsal-abc",
)


def test_the_override_publishes_the_given_ports_on_loopback_only() -> None:
    assert '"127.0.0.1:41001:5432"' in OVERRIDE
    assert '"127.0.0.1:41002:8000"' in OVERRIDE
    assert OVERRIDE.count("ports: !override") == 2
    assert "5433" not in OVERRIDE
    assert ":8000:8000" not in OVERRIDE


def test_the_override_names_one_image_per_side_through_the_environment() -> None:
    image = "image: neuromesh-app:rehearsal-abc-${REHEARSAL_SIDE}"

    assert OVERRIDE.count(image) == 2


def test_the_override_points_the_secret_at_the_file_of_this_run() -> None:
    assert 'file: "/tmp/run/postgres_password"' in OVERRIDE


# A child process that enters the environment with every command faked.
# It records the commands, writes the temporary directory it was given
# and then waits to be terminated.
CHILD = """
import io
import sys
import tarfile
import time
from pathlib import Path

import scripts.upgrade_rehearsal as rehearsal

log = Path(sys.argv[1])
state = Path(sys.argv[2])
buffer = io.BytesIO()
tarfile.open(fileobj=buffer, mode="w").close()
EMPTY_TAR = buffer.getvalue()


def fake_run(command, *, cwd=None, env=None, check=True):
    with log.open("a") as handle:
        handle.write(" ".join(command) + "\\n")
    stdout = "a" * 40 + "\\n" if list(command[:2]) == ["git", "rev-parse"] else ""
    return rehearsal.subprocess.CompletedProcess(list(command), 0, stdout, "")


rehearsal._run = fake_run
rehearsal._archive = lambda sha: EMPTY_TAR
with rehearsal.rehearsal_environment("old", "new") as environment:
    partial = state.with_suffix(".partial")
    partial.write_text(str(environment.root))
    partial.rename(state)
    time.sleep(60)
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "marker.txt").write_text("release one\n")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=rehearsal",
        "-c",
        "user.email=rehearsal@example.com",
        "commit",
        "-q",
        "-m",
        "one",
    )
    return repo


def _worktrees(repo: Path) -> list[str]:
    listing = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in listing.splitlines() if line.startswith("worktree ")]


def _fake_docker(monkeypatch: pytest.MonkeyPatch, *, containers_left: bool) -> None:
    real_run = rehearsal._run

    def run(command: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command[0] == "docker":
            listing = "deadbeef\n" if containers_left and command[1:2] == ["ps"] else ""
            return subprocess.CompletedProcess(list(command), 0, listing, "")
        return real_run(command, **kwargs)

    monkeypatch.setattr(rehearsal, "_run", run)


def test_a_terminated_run_still_cleans_up(tmp_path: Path) -> None:
    log = tmp_path / "commands.log"
    state = tmp_path / "root.txt"
    child = subprocess.Popen(
        [sys.executable, "-c", CHILD, str(log), str(state)],
        cwd=REPO_ROOT,
    )
    root: Path | None = None

    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not state.exists():
            time.sleep(0.05)
        assert state.exists(), "the child never created its environment"
        root = Path(state.read_text())

        child.send_signal(signal.SIGTERM)
        child.wait(timeout=15)

        commands = log.read_text().splitlines() if log.exists() else []
        assert any(" down -v " in line for line in commands), (
            "SIGTERM ended the run without the cleanup"
        )
        assert not root.exists(), "the temporary directory of a terminated run was left"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        if root is not None and root.name.startswith("upgrade-rehearsal-"):
            shutil.rmtree(root, ignore_errors=True)


def test_the_exported_sides_hold_the_files_and_no_git_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rehearsal, "REPO_ROOT", _make_repo(tmp_path))
    _fake_docker(monkeypatch, containers_left=False)

    with rehearsal.rehearsal_environment("HEAD", "HEAD") as environment:
        for side in (environment.old_dir, environment.new_dir):
            assert (side / "marker.txt").read_text() == "release one\n"
            assert not (side / ".git").exists(), (
                "the exported tree must not point back at the repository"
            )


def test_the_two_sides_register_no_worktree_in_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(rehearsal, "REPO_ROOT", repo)
    _fake_docker(monkeypatch, containers_left=False)

    with rehearsal.rehearsal_environment("HEAD", "HEAD"):
        assert len(_worktrees(repo)) == 1, (
            "the two sides must not register worktrees in the repository"
        )


def test_a_cleanup_that_leaves_a_container_behind_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rehearsal, "REPO_ROOT", _make_repo(tmp_path))
    _fake_docker(monkeypatch, containers_left=True)

    with pytest.raises(SystemExit) as raised:
        with rehearsal.rehearsal_environment("HEAD", "HEAD"):
            pass

    assert "left behind" in str(raised.value)


def test_a_clean_teardown_reports_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rehearsal, "REPO_ROOT", _make_repo(tmp_path))
    _fake_docker(monkeypatch, containers_left=False)

    with rehearsal.rehearsal_environment("HEAD", "HEAD") as environment:
        root = environment.root

    assert not root.exists()
