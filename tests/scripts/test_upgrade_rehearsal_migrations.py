from __future__ import annotations

import contextlib
import subprocess
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from scripts import upgrade_rehearsal

Migrations = dict[str, dict[str, str]]

SEEDED = {
    "public.nodes": "id,tenant_id\n1,a\n",
    "public.workers": "id,tenant_id\n1,a\n",
    "public.jobs": "id,tenant_id\n1,a\n",
    "public.leases": "id,tenant_id\n1,a\n",
}

MIGRATE = "compose new run --rm --no-deps migrate"


def migration(version: int, name: str, checksum: str) -> dict[str, str]:
    return {"version": str(version), "name": name, "checksum": checksum}


BEFORE: Migrations = {
    "3": migration(3, "three", "c3"),
    "4": migration(4, "four", "c4"),
}
AFTER: Migrations = {**BEFORE, "5": migration(5, "five", "c5")}


def test_a_run_that_adds_a_version_has_no_problems() -> None:
    assert upgrade_rehearsal.compare_migrations(BEFORE, AFTER) == []


def test_a_run_that_adds_nothing_is_a_problem() -> None:
    assert upgrade_rehearsal.compare_migrations(BEFORE, BEFORE) == [
        "the upgrade applied no migration"
    ]


def test_an_applied_version_missing_afterwards_is_named() -> None:
    after = {k: v for k, v in AFTER.items() if k != "3"}

    assert upgrade_rehearsal.compare_migrations(BEFORE, after) == [
        "schema_migrations 3: applied before the upgrade and missing "
        "after it"
    ]


@pytest.mark.parametrize(
    ("column", "new"), [("name", "renamed"), ("checksum", "zzz")]
)
def test_a_changed_name_or_checksum_is_named(column: str, new: str) -> None:
    after = {
        **AFTER,
        "4": {**BEFORE["4"], column: new},
    }
    old = BEFORE["4"][column]

    assert upgrade_rehearsal.compare_migrations(BEFORE, after) == [
        f"schema_migrations 4: {column} changed from {old!r} to {new!r}"
    ]


def test_every_problem_is_reported_not_only_the_first() -> None:
    after: Migrations = {"4": BEFORE["4"]}

    assert upgrade_rehearsal.compare_migrations(BEFORE, after) == [
        "schema_migrations 3: applied before the upgrade and missing "
        "after it",
        "the upgrade applied no migration",
    ]


def test_versions_are_reported_in_numeric_order() -> None:
    before: Migrations = {
        "9": migration(9, "nine", "c9"),
        "10": migration(10, "ten", "c10"),
    }
    after: Migrations = {"11": migration(11, "eleven", "c11")}

    assert upgrade_rehearsal.compare_migrations(before, after)[:2] == [
        "schema_migrations 9: applied before the upgrade and missing "
        "after it",
        "schema_migrations 10: applied before the upgrade and missing "
        "after it",
    ]


def test_the_added_versions_are_listed_with_their_names() -> None:
    assert upgrade_rehearsal.added_migrations(BEFORE, AFTER) == ["5 five"]


def test_the_export_of_schema_migrations_is_read_by_version() -> None:
    text = "version,name,checksum\n3,three,c3\n4,four,c4\n"

    assert upgrade_rehearsal.read_migrations(text) == BEFORE


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
        self.events.append(f"compose {side} {' '.join(args)}")
        stdout = "127.0.0.1:49153\n" if args[0] == "port" else ""
        return subprocess.CompletedProcess(list(args), 0, stdout, "")


def wire(
    monkeypatch: pytest.MonkeyPatch,
    migrations: list[Migrations],
) -> Recorder:
    recorder = Recorder()
    events = recorder.events
    snapshots = iter([SEEDED, SEEDED])
    reads = iter(migrations)

    @contextlib.contextmanager
    def fake_environment(old_ref: str, new_ref: str) -> Iterator[Recorder]:
        yield recorder

    def fake_snapshot(compose: object) -> dict[str, str]:
        events.append("snapshot")
        return next(snapshots)

    def fake_migrations(compose: object) -> Migrations:
        events.append("migrations")
        return next(reads)

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
        "fresh_schema": lambda old, new: SCHEMA,
        "schema_dump": lambda compose, database: SCHEMA,
        "start_new_api": lambda compose: 49153,
        "read_back": lambda get, ids: None,
        "stop_new_api": lambda compose, inspect: None,
    }
    for name, fake in patches.items():
        monkeypatch.setattr(upgrade_rehearsal, name, fake)
    # raising=False lets these tests run, and fail for the right
    # reason, before the function exists.
    monkeypatch.setattr(
        upgrade_rehearsal, "applied_migrations", fake_migrations, raising=False
    )
    return recorder


def test_the_versions_are_read_before_and_after_the_migrate_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = wire(monkeypatch, [BEFORE, AFTER])

    assert upgrade_rehearsal.main(["--old", "v0.6.0"]) == 0

    events = recorder.events
    reads = [i for i, e in enumerate(events) if e == "migrations"]
    assert len(reads) == 2
    assert events.index("snapshot") < reads[0] < events.index(MIGRATE) < reads[1]


def test_the_added_versions_are_printed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wire(monkeypatch, [BEFORE, AFTER])

    assert upgrade_rehearsal.main(["--old", "v0.6.0"]) == 0

    assert "applied migration 5 five" in capsys.readouterr().out


def test_a_run_that_applies_nothing_fails_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire(monkeypatch, [BEFORE, BEFORE])

    with pytest.raises(RuntimeError, match="applied no migration"):
        upgrade_rehearsal.main(["--old", "v0.6.0"])


def test_a_missing_applied_version_ends_the_run_and_names_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    after = {k: v for k, v in AFTER.items() if k != "3"}
    wire(monkeypatch, [BEFORE, after])

    with pytest.raises(RuntimeError, match="schema_migrations 3"):
        upgrade_rehearsal.main(["--old", "v0.6.0"])


def test_a_changed_checksum_ends_the_run_and_names_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    after = {**AFTER, "4": {**BEFORE["4"], "checksum": "zzz"}}
    wire(monkeypatch, [BEFORE, after])

    with pytest.raises(RuntimeError, match="checksum changed"):
        upgrade_rehearsal.main(["--old", "v0.6.0"])
