from __future__ import annotations

import contextlib
import subprocess
from collections.abc import Callable, Iterator, Sequence
from types import SimpleNamespace

import pytest

from scripts import upgrade_rehearsal

SEEDED = {
    "public.nodes": "id\n1\n",
    "public.workers": "id\n1\n",
    "public.jobs": "id\n1\n",
    "public.leases": "id\n1\n",
}


class Recorder:
    def __init__(self) -> None:
        self.events: list[str] = []

    def compose(
        self,
        side: str,
        *args: str,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.events.append(f"compose {args[0]}")
        stdout = "127.0.0.1:49153\n" if args[0] == "port" else ""
        return subprocess.CompletedProcess(list(args), 0, stdout, "")


def wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    snapshot: dict[str, str],
    stop: Callable[[object, object], None] | None = None,
) -> Recorder:
    recorder = Recorder()
    events = recorder.events

    @contextlib.contextmanager
    def fake_environment(old_ref: str, new_ref: str) -> Iterator[Recorder]:
        yield recorder

    def fake_stop(compose: object, inspect: object) -> None:
        events.append("stop")

    def fake_snapshot(compose: object) -> dict[str, str]:
        events.append("snapshot")
        return snapshot

    patches: dict[str, object] = {
        "rehearsal_environment": fake_environment,
        "issue_key": lambda runner: "k",
        "http_post": lambda base_url, key: "post",
        "seed_cluster": lambda post: SimpleNamespace(
            node="n", worker="w", job="j"
        ),
        "stage": lambda message: events.append(f"stage: {message}"),
        "at_rest": lambda compose: events.append("rest"),
        "stop_old_api": stop or fake_stop,
        "snapshot": fake_snapshot,
    }
    for name, fake in patches.items():
        monkeypatch.setattr(upgrade_rehearsal, name, fake)
    return recorder


def test_the_old_side_is_brought_to_rest_before_it_is_exported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = wire(monkeypatch, snapshot=SEEDED)

    assert upgrade_rehearsal.main(["--old", "v0.6.0"]) == 0

    steps = [e for e in recorder.events if not e.startswith("compose")]
    assert steps == [
        "stage: preparing the two releases",
        "stage: building and starting the old release "
        f"(limit {upgrade_rehearsal.BUILD_TIMEOUT:g}s)",
        "stage: issuing the API key",
        "stage: seeding the cluster through the API",
        "stage: waiting for the seeded cluster to settle",
        "rest",
        "stage: stopping the old API",
        "stop",
        "stage: exporting the tables before the upgrade",
        "snapshot",
        "stage: checking that the seed left data in every required table",
    ]


def test_an_empty_seed_ends_the_run_naming_the_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = {**SEEDED, "public.leases": "id\n"}
    recorder = wire(monkeypatch, snapshot=empty)

    with pytest.raises(RuntimeError, match=r"public\.leases: has no rows"):
        upgrade_rehearsal.main(["--old", "v0.6.0"])

    assert recorder.events[-1] == (
        "stage: checking that the seed left data in every required table"
    )


def test_a_failed_stop_never_reaches_the_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_stop(compose: object, inspect: object) -> None:
        raise RuntimeError("the API was killed (exit code 137), not stopped")

    recorder = wire(monkeypatch, snapshot=SEEDED, stop=failing_stop)

    with pytest.raises(RuntimeError, match="killed"):
        upgrade_rehearsal.main(["--old", "v0.6.0"])

    assert "snapshot" not in recorder.events


def test_docker_inspect_asks_for_the_status_and_the_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Sequence[str]] = []

    def fake_run(
        command: Sequence[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        return subprocess.CompletedProcess(list(command), 0, "exited 0\n", "")

    monkeypatch.setattr(upgrade_rehearsal, "_run", fake_run)

    assert upgrade_rehearsal.docker_inspect("abc123") == "exited 0\n"
    assert seen == [
        [
            "docker",
            "inspect",
            "--format",
            "{{.State.Status}} {{.State.ExitCode}}",
            "abc123",
        ]
    ]
