from __future__ import annotations

import contextlib
import subprocess
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from scripts import upgrade_rehearsal

SEEDED = {
    "public.nodes": "id,tenant_id\n1,a\n",
    "public.workers": "id,tenant_id\n1,a\n",
    "public.jobs": "id,tenant_id\n1,a\n",
    "public.leases": "id,tenant_id\n1,a\n",
}

MIGRATE = "compose new run --rm --no-deps migrate"


VERSIONS = {"4": {"version": "4", "name": "four", "checksum": "c4"}}
UPGRADED = {
    **VERSIONS,
    "5": {"version": "5", "name": "five", "checksum": "c5"},
}


SCHEMA = "CREATE TABLE public.nodes (id uuid);"


class Recorder:
    def __init__(self, *, fail_migrate: bool = False) -> None:
        self.events: list[str] = []
        self.fail_migrate = fail_migrate

    def compose(
        self,
        side: str,
        *args: str,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.events.append(f"compose {side} {' '.join(args)}")
        if self.fail_migrate and side == "new" and args[0] == "run":
            raise subprocess.CalledProcessError(
                1, list(args), "", "migration 0005 refused"
            )
        stdout = "127.0.0.1:49153\n" if args[0] == "port" else ""
        return subprocess.CompletedProcess(list(args), 0, stdout, "")


def wire(
    monkeypatch: pytest.MonkeyPatch,
    snapshots: list[dict[str, str]],
    *,
    fail_migrate: bool = False,
) -> Recorder:
    recorder = Recorder(fail_migrate=fail_migrate)
    events = recorder.events
    reads = iter([VERSIONS, UPGRADED])
    remaining = iter(snapshots)

    @contextlib.contextmanager
    def fake_environment(old_ref: str, new_ref: str) -> Iterator[Recorder]:
        yield recorder

    def fake_snapshot(compose: object) -> dict[str, str]:
        events.append("snapshot")
        return next(remaining)

    patches: dict[str, object] = {
        "rehearsal_environment": fake_environment,
        "issue_key": lambda runner: "k",
        "http_post": lambda base_url, key: "post",
        "seed_cluster": lambda post: SimpleNamespace(
            node="n", worker="w", job="j"
        ),
        "stage": lambda message: events.append(f"stage: {message}"),
        "at_rest": lambda compose: events.append("rest"),
        "stop_old_api": lambda compose, inspect: events.append("stop"),
        "snapshot": fake_snapshot,
        "applied_migrations": lambda compose: next(reads),
        "fresh_schema": lambda old, new: SCHEMA,
        "schema_dump": lambda compose, database: SCHEMA,
        "start_new_api": lambda compose: 49153,
        "read_back": lambda get, ids: None,
        "stop_new_api": lambda compose, inspect: None,
    }
    for name, fake in patches.items():
        monkeypatch.setattr(upgrade_rehearsal, name, fake)
    return recorder


def test_only_the_build_and_the_migrate_service_run_on_the_new_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = wire(monkeypatch, [SEEDED, SEEDED])

    assert upgrade_rehearsal.main(["--old", "v0.6.0"]) == 0

    new_side = [e for e in recorder.events if e.startswith("compose new ")]
    assert new_side == [
        "compose new build neuromesh",
        MIGRATE,
    ]


def test_the_new_image_is_built_then_migrated_then_exported_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = wire(monkeypatch, [SEEDED, SEEDED])

    assert upgrade_rehearsal.main(["--old", "v0.6.0"]) == 0

    events = recorder.events
    first = events.index("snapshot")
    second = events.index("snapshot", first + 1)
    build = events.index("compose new build neuromesh")
    migrate = events.index(MIGRATE)
    assert first < build < migrate < second


def test_a_failed_migrate_ends_the_run_without_a_second_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = wire(monkeypatch, [SEEDED, SEEDED], fail_migrate=True)

    with pytest.raises(subprocess.CalledProcessError):
        upgrade_rehearsal.main(["--old", "v0.6.0"])

    assert recorder.events.count("snapshot") == 1


def test_a_changed_row_ends_the_run_and_names_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed = {**SEEDED, "public.workers": "id,tenant_id\n1,b\n"}
    wire(monkeypatch, [SEEDED, changed])

    with pytest.raises(
        RuntimeError,
        match=r"public\.workers 1: tenant_id changed from 'a' to 'b'",
    ):
        upgrade_rehearsal.main(["--old", "v0.6.0"])
