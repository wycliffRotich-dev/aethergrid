from __future__ import annotations

import contextlib
import subprocess
from collections.abc import Iterator, Sequence
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

VERSIONS: Migrations = {
    "4": {"version": "4", "name": "four", "checksum": "c4"}
}
UPGRADED_VERSIONS: Migrations = {
    **VERSIONS,
    "5": {"version": "5", "name": "five", "checksum": "c5"},
}

NODES = (
    "CREATE TABLE public.nodes (",
    "    id uuid NOT NULL,",
    "    tenant_id text NOT NULL",
    ");",
)
INDEX = "CREATE INDEX extra ON public.nodes (id);"
ONLY_UPGRADED = "only in the upgraded schema: "
ONLY_FRESH = "only in the fresh schema: "


def dump(*lines: str, key: str = "k1") -> str:
    body = "\n".join(lines)
    return f"\\restrict {key}\n{body}\n\\unrestrict {key}\n"


UPGRADED_SCHEMA = dump(*NODES, key="k1")
FRESH_SCHEMA = dump(*NODES, key="k2")


def completed(
    stdout: str = "", code: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


def test_dumps_that_differ_only_in_the_random_key_match() -> None:
    assert upgrade_rehearsal.compare_schemas(
        UPGRADED_SCHEMA, FRESH_SCHEMA
    ) == []


def test_the_random_key_lines_are_not_counted() -> None:
    assert upgrade_rehearsal.schema_lines(UPGRADED_SCHEMA) == list(NODES)


def test_a_line_only_in_the_upgraded_dump_is_named() -> None:
    upgraded = dump(*NODES, INDEX, key="k1")

    assert upgrade_rehearsal.compare_schemas(upgraded, FRESH_SCHEMA) == [
        ONLY_UPGRADED + INDEX
    ]


def test_a_line_only_in_the_fresh_dump_is_named() -> None:
    fresh = dump(*NODES, INDEX, key="k2")

    assert upgrade_rehearsal.compare_schemas(UPGRADED_SCHEMA, fresh) == [
        ONLY_FRESH + INDEX
    ]


def test_a_changed_line_is_named_on_both_sides() -> None:
    changed = (NODES[0], NODES[1], "    tenant_id text NULL", NODES[3])
    upgraded = dump(*changed, key="k1")

    assert upgrade_rehearsal.compare_schemas(upgraded, FRESH_SCHEMA) == [
        ONLY_UPGRADED + changed[2],
        ONLY_FRESH + NODES[2],
    ]


def test_every_difference_is_reported_not_only_the_first() -> None:
    upgraded = dump(*NODES, "A;", "B;", key="k1")

    assert upgrade_rehearsal.compare_schemas(upgraded, FRESH_SCHEMA) == [
        ONLY_UPGRADED + "A;",
        ONLY_UPGRADED + "B;",
    ]


@pytest.mark.parametrize(
    "empty",
    ["", "\\restrict k\n\\unrestrict k\n", "-- only a comment\n"],
)
def test_two_dumps_with_no_table_are_a_problem(empty: str) -> None:
    assert upgrade_rehearsal.compare_schemas(empty, empty) == [
        "the upgraded schema has no CREATE TABLE line",
        "the fresh schema has no CREATE TABLE line",
    ]


def test_a_fresh_dump_with_no_table_is_named_before_the_differences() -> None:
    problems = upgrade_rehearsal.compare_schemas(UPGRADED_SCHEMA, "")

    assert problems[0] == "the fresh schema has no CREATE TABLE line"
    assert len(problems) == 1 + len(NODES)


def test_the_schema_is_dumped_with_pg_dump_schema_only_and_no_owner() -> None:
    seen: list[Sequence[str]] = []

    def compose(
        arguments: Sequence[str],
    ) -> subprocess.CompletedProcess[str]:
        seen.append(arguments)
        return completed(UPGRADED_SCHEMA)

    assert upgrade_rehearsal.schema_dump(compose, "neuromesh") == UPGRADED_SCHEMA
    assert seen == [
        [
            "exec", "-T", "postgres", "pg_dump", "-U", "neuromesh",
            "-d", "neuromesh", "--schema-only", "--no-owner",
        ]
    ]


def test_a_failed_dump_reports_the_exit_code_and_stderr_not_stdout() -> None:
    def compose(
        arguments: Sequence[str],
    ) -> subprocess.CompletedProcess[str]:
        return completed("table data", 2, "connection refused")

    with pytest.raises(
        RuntimeError, match="exit code 2: connection refused"
    ) as caught:
        upgrade_rehearsal.schema_dump(compose, "neuromesh")

    assert "table data" not in str(caught.value)


def test_the_fresh_database_is_created_migrated_and_dumped() -> None:
    events: list[str] = []

    def old(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        events.append("old " + " ".join(arguments))
        return completed(FRESH_SCHEMA if "pg_dump" in arguments else "")

    def new(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        events.append("new " + " ".join(arguments))
        return completed()

    assert upgrade_rehearsal.fresh_schema(old, new) == FRESH_SCHEMA
    assert events == [
        "old exec -T postgres psql -U neuromesh -d neuromesh -At -c "
        "CREATE DATABASE schema_fresh",
        "new run --rm --no-deps -e "
        "NEUROMESH_DATABASE_URL=postgresql://neuromesh@postgres:5432/"
        "schema_fresh migrate",
        "old exec -T postgres pg_dump -U neuromesh -d schema_fresh "
        "--schema-only --no-owner",
    ]


def test_a_failed_create_never_reaches_the_migrate() -> None:
    events: list[str] = []

    def old(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return completed("", 1, "already exists")

    def new(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        events.append("new")
        return completed()

    with pytest.raises(RuntimeError, match="creating the fresh database"):
        upgrade_rehearsal.fresh_schema(old, new)

    assert events == []


def test_a_failed_migrate_never_reaches_the_dump() -> None:
    events: list[str] = []

    def old(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        events.append(" ".join(arguments))
        return completed()

    def new(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, list(arguments), "", "refused")

    with pytest.raises(subprocess.CalledProcessError):
        upgrade_rehearsal.fresh_schema(old, new)

    assert not any("pg_dump" in event for event in events)


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
    monkeypatch: pytest.MonkeyPatch, upgraded: str, fresh: str
) -> Recorder:
    recorder = Recorder()
    events = recorder.events
    snapshots = iter([SEEDED, SEEDED])
    reads = iter([VERSIONS, UPGRADED_VERSIONS])

    @contextlib.contextmanager
    def fake_environment(old_ref: str, new_ref: str) -> Iterator[Recorder]:
        yield recorder

    def fake_snapshot(compose: object) -> dict[str, str]:
        events.append("snapshot")
        return next(snapshots)

    def fake_fresh_schema(old: object, new: object) -> str:
        events.append("fresh_schema")
        return fresh

    def fake_schema_dump(compose: object, database: str) -> str:
        events.append("schema_dump")
        return upgraded

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
        "start_new_api": lambda compose: 49153,
        "read_back": lambda get, ids: None,
        "stop_new_api": lambda compose, inspect: None,
    }
    for name, fake in patches.items():
        monkeypatch.setattr(upgrade_rehearsal, name, fake)
    # raising=False lets these tests run, and fail for the right
    # reason, before the functions exist.
    monkeypatch.setattr(
        upgrade_rehearsal, "fresh_schema", fake_fresh_schema, raising=False
    )
    monkeypatch.setattr(
        upgrade_rehearsal, "schema_dump", fake_schema_dump, raising=False
    )
    return recorder


def test_the_schemas_are_compared_after_the_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = wire(monkeypatch, UPGRADED_SCHEMA, FRESH_SCHEMA)

    assert upgrade_rehearsal.main(["--old", "v0.6.0"]) == 0

    events = recorder.events
    tables = events.index(
        "stage: comparing the tables before and after the upgrade"
    )
    building = events.index(
        "stage: building a fresh database with the new migrations"
    )
    fresh = events.index("fresh_schema")
    dumping = events.index(
        "stage: dumping the schema of the upgraded database"
    )
    upgraded = events.index("schema_dump")
    comparing = events.index("stage: comparing the two schemas")
    assert tables < building < fresh < dumping < upgraded < comparing


def test_a_match_prints_the_number_of_lines_compared(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wire(monkeypatch, UPGRADED_SCHEMA, FRESH_SCHEMA)

    assert upgrade_rehearsal.main(["--old", "v0.6.0"]) == 0

    assert (
        "the upgraded schema matches a fresh one (4 lines)"
        in capsys.readouterr().out
    )


def test_a_difference_ends_the_run_and_names_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fresh = dump(*NODES, INDEX, key="k2")
    wire(monkeypatch, UPGRADED_SCHEMA, fresh)

    with pytest.raises(
        RuntimeError, match="only in the fresh schema: CREATE INDEX extra"
    ):
        upgrade_rehearsal.main(["--old", "v0.6.0"])


def test_two_dumps_with_no_table_end_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire(monkeypatch, "", "")

    with pytest.raises(RuntimeError, match="has no CREATE TABLE line"):
        upgrade_rehearsal.main(["--old", "v0.6.0"])
