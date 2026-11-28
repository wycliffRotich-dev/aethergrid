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

VERSIONS = {"4": {"version": "4", "name": "four", "checksum": "c4"}}
UPGRADED = {
    **VERSIONS,
    "5": {"version": "5", "name": "five", "checksum": "c5"},
}


SCHEMA = "CREATE TABLE public.nodes (id uuid);"


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
    after: dict[str, str] | None = None,
    stop: Callable[[object, object], None] | None = None,
) -> Recorder:
    recorder = Recorder()
    events = recorder.events
    reads = iter([VERSIONS, UPGRADED])
    exports = iter([snapshot, snapshot if after is None else after])

    @contextlib.contextmanager
    def fake_environment(old_ref: str, new_ref: str) -> Iterator[Recorder]:
        yield recorder

    def fake_stop(compose: object, inspect: object) -> None:
        events.append("stop")

    def fake_snapshot(compose: object) -> dict[str, str]:
        events.append("snapshot")
        return next(exports)

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
        "applied_migrations": lambda compose: next(reads),
        "fresh_schema": lambda old, new: SCHEMA,
        "schema_dump": lambda compose, database: SCHEMA,
        "start_new_api": lambda compose: 49153,
        "read_back": lambda get, ids, **extra: None,
        "stop_new_api": lambda compose, inspect: None,
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
        "stage: building the new release "
        f"(limit {upgrade_rehearsal.BUILD_TIMEOUT:g}s)",
        "stage: applying the new migrations to the seeded database",
        "stage: exporting the tables after the upgrade",
        "snapshot",
        "stage: comparing the tables before and after the upgrade",
        "stage: building a fresh database with the new migrations",
        "stage: dumping the schema of the upgraded database",
        "stage: comparing the two schemas",
        "stage: starting the new API on the upgraded database",
        "stage: reading back the seeded rows through the new API",
        "stage: stopping the new API",
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


CREATED = {
    "public.public_demo_scope": "tenant_id\n",
    "public.lease_reclaims": "id,tenant_id\n",
    "public.lease_refusals": "id,tenant_id\n",
}
SUCCESS = "the upgrade changed nothing in 4 tables"


def test_the_success_line_counts_the_tables_of_the_export_before(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(monkeypatch, snapshot=SEEDED, after={**SEEDED, **CREATED})

    assert upgrade_rehearsal.main(["--old", "v0.7.0"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert SUCCESS in lines
    assert "the upgrade changed nothing in 7 tables" not in lines


def test_each_created_table_is_printed_after_the_success_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(monkeypatch, snapshot=SEEDED, after={**SEEDED, **CREATED})

    assert upgrade_rehearsal.main(["--old", "v0.7.0"]) == 0

    lines = capsys.readouterr().out.splitlines()
    start = lines.index(SUCCESS)
    assert lines[start + 1 : start + 4] == [
        "the upgrade created the table public.lease_reclaims",
        "the upgrade created the table public.lease_refusals",
        "the upgrade created the table public.public_demo_scope",
    ]


def test_a_created_table_with_rows_ends_the_run_at_the_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filled = {**SEEDED, "public.lease_reclaims": "id,tenant_id\nc1,t1\n"}
    recorder = wire(monkeypatch, snapshot=SEEDED, after=filled)

    with pytest.raises(
        RuntimeError,
        match=r"public\.lease_reclaims: created by the upgrade, rows: 1",
    ):
        upgrade_rehearsal.main(["--old", "v0.7.0"])

    assert recorder.events[-1] == (
        "stage: comparing the tables before and after the upgrade"
    )


def test_a_run_with_no_created_table_prints_no_created_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wire(monkeypatch, snapshot=SEEDED)

    assert upgrade_rehearsal.main(["--old", "v0.7.0"]) == 0

    out = capsys.readouterr().out
    assert "the upgrade created the table" not in out
    assert SUCCESS in out.splitlines()
