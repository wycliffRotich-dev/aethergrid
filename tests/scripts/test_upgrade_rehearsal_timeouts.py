from __future__ import annotations

import contextlib
import re
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import upgrade_rehearsal


class FakeRun:
    """Stands in for subprocess.run and keeps what it was called with."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.kwargs: dict[str, Any] = {}

    def __call__(
        self,
        command: Sequence[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(list(command), 0, "", "")


def make_environment(tmp_path: Path) -> upgrade_rehearsal.Environment:
    return upgrade_rehearsal.Environment(
        root=tmp_path,
        old_dir=tmp_path / "old",
        new_dir=tmp_path / "new",
        project="upgrade-rehearsal-test",
        override=tmp_path / "override.yml",
        tag_prefix="rehearsal-test",
    )


def test_a_command_runs_under_the_default_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake = FakeRun()
    monkeypatch.setattr(subprocess, "run", fake)

    make_environment(tmp_path).compose("old", "ps")

    assert fake.kwargs["timeout"] == upgrade_rehearsal.DEFAULT_COMMAND_TIMEOUT


def test_a_command_can_be_given_its_own_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake = FakeRun()
    monkeypatch.setattr(subprocess, "run", fake)

    make_environment(tmp_path).compose("old", "up", timeout=7.5)

    assert fake.kwargs["timeout"] == 7.5


def test_a_timeout_names_the_command_and_the_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeRun(subprocess.TimeoutExpired(["docker"], 7.5))
    monkeypatch.setattr(subprocess, "run", fake)

    with pytest.raises(subprocess.TimeoutExpired):
        make_environment(tmp_path).compose("old", "up", timeout=7.5)

    error = capsys.readouterr().err
    assert "docker compose -p upgrade-rehearsal-test" in error
    assert "timed out after 7.5s" in error


def test_a_timeout_is_raised_even_when_the_failure_is_tolerated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake = FakeRun(subprocess.TimeoutExpired(["docker"], 1.0))
    monkeypatch.setattr(subprocess, "run", fake)

    with pytest.raises(subprocess.TimeoutExpired):
        make_environment(tmp_path).compose("old", "ps", check=False)


@pytest.fixture
def hanging_docker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    """A machine where every docker command runs out of time."""
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
            raise subprocess.TimeoutExpired(list(command), 120.0)
        return subprocess.CompletedProcess(list(command), 0, "", "")

    monkeypatch.setattr(upgrade_rehearsal, "_run", run)
    return tmp_path


def test_a_cleanup_that_times_out_does_not_hide_the_error_of_the_run(
    hanging_docker: Path,
) -> None:
    with (
        pytest.raises(RuntimeError, match="the run failed"),
        upgrade_rehearsal.rehearsal_environment("old", "new"),
    ):
        raise RuntimeError("the run failed")

    assert list(hanging_docker.glob("upgrade-rehearsal-*")) == []


def test_a_stage_line_goes_to_stderr_with_the_time(
    capsys: pytest.CaptureFixture[str],
) -> None:
    upgrade_rehearsal.stage("building")

    captured = capsys.readouterr()
    assert re.fullmatch(r"\d\d:\d\d:\d\d ==> building\n", captured.err)
    assert captured.out == ""


class FakeEnvironment:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def compose(
        self,
        side: str,
        *args: str,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if timeout is None:
            timeout = upgrade_rehearsal.DEFAULT_COMMAND_TIMEOUT
        self.events.append(f"compose {args[0]} timeout={timeout:g}")
        stdout = "127.0.0.1:49153\n" if args[0] == "port" else ""
        return subprocess.CompletedProcess(list(args), 0, stdout, "")


def test_each_step_of_a_run_is_announced_before_it_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    environment = FakeEnvironment(events)

    @contextlib.contextmanager
    def fake_environment(
        old_ref: str,
        new_ref: str,
    ) -> Iterator[FakeEnvironment]:
        yield environment

    def fake_issue_key(runner: object) -> str:
        events.append("key")
        return "k"

    def fake_http_post(base_url: str, key: str) -> str:
        events.append(f"http {base_url}")
        return "post"

    def fake_seed(post: object) -> SimpleNamespace:
        events.append("seed")
        return SimpleNamespace(node="n", worker="w", job="j")

    def fake_stage(message: str) -> None:
        events.append(f"stage: {message}")

    for name, fake in (
        ("rehearsal_environment", fake_environment),
        ("issue_key", fake_issue_key),
        ("http_post", fake_http_post),
        ("seed_cluster", fake_seed),
        ("stage", fake_stage),
    ):
        monkeypatch.setattr(upgrade_rehearsal, name, fake)

    assert upgrade_rehearsal.main(["--old", "v0.6.0"]) == 0

    build = upgrade_rehearsal.BUILD_TIMEOUT
    default = upgrade_rehearsal.DEFAULT_COMMAND_TIMEOUT
    assert events == [
        "stage: preparing the two releases",
        f"stage: building and starting the old release (limit {build:g}s)",
        f"compose up timeout={build:g}",
        f"compose port timeout={default:g}",
        "stage: issuing the API key",
        "key",
        "stage: seeding the cluster through the API",
        "http http://127.0.0.1:49153",
        "seed",
    ]
