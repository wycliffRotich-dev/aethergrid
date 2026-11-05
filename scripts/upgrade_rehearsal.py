"""
Pieces of the upgrade rehearsal (ADR 0075, condition 5).

The rehearsal seeds a database with one release, upgrades it with the
migrations of the next, and shows that no row changed. This module
holds the part that decides whether anything did.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import difflib
import io
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any

Snapshot = dict[str, str]
# Applied migrations by version, each with its name and checksum.
Migrations = dict[str, dict[str, str]]

# How an export writes a null, so that it stays apart from an empty string.
NULL_MARKER = "\\N"

# The tables of every schema but the system ones, quoted by Postgres
# itself. schema_migrations is left out because it changes on every
# upgrade by design.
TABLES_SQL = """
SELECT format('%I.%I', schemaname, tablename)
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
  AND tablename <> 'schema_migrations'
ORDER BY 1
"""


def copy_sql(table: str) -> str:
    """
    The statement that exports one table as CSV with a header, a null
    written as the null marker. The table must be a name taken from
    TABLES_SQL, which has already quoted its identifiers.
    """
    return (
        f"COPY {table} TO STDOUT "
        f"WITH (FORMAT csv, HEADER, NULL '{NULL_MARKER}')"
    )


def _read(
    table: str,
    text: str,
) -> tuple[list[str], dict[str, dict[str, str]]]:
    # The csv module drops quotes, so a text value equal to the marker
    # (which COPY writes quoted) could not be told from a null.
    if f'"{NULL_MARKER}"' in text:
        raise ValueError(
            f"{table}: the export holds a quoted {NULL_MARKER}, which "
            "cannot be told from the null marker"
        )

    reader = csv.DictReader(io.StringIO(text))
    columns = list(reader.fieldnames or [])
    if not columns:
        raise ValueError(f"{table}: the export has no header")

    rows: dict[str, dict[str, str]] = {}
    for row in reader:
        if None in row or None in row.values():
            raise ValueError(
                f"{table}: line {reader.line_num} has the wrong number "
                "of fields"
            )
        row_id = row[columns[0]]
        if row_id in rows:
            raise ValueError(f"{table}: id {row_id} appears twice")
        rows[row_id] = row

    return columns, rows


def compare_snapshots(before: Snapshot, after: Snapshot) -> list[str]:
    """
    Compare two sets of table exports, each a table name mapped to CSV
    text with a header whose first column is the id. Return one line
    per difference, or an empty list when nothing changed.
    """
    differences: list[str] = []

    for table in sorted(set(before) | set(after)):
        if table not in before:
            differences.append(f"{table}: missing from the before snapshot")
            continue
        if table not in after:
            differences.append(f"{table}: missing from the after snapshot")
            continue

        before_columns, before_rows = _read(table, before[table])
        after_columns, after_rows = _read(table, after[table])

        if before_columns != after_columns:
            differences.append(
                f"{table}: columns changed from {before_columns} "
                f"to {after_columns}"
            )
            continue

        for row_id in sorted(before_rows.keys() - after_rows.keys()):
            differences.append(f"{table} {row_id}: row removed")
        for row_id in sorted(after_rows.keys() - before_rows.keys()):
            differences.append(f"{table} {row_id}: row added")
        for row_id in sorted(before_rows.keys() & after_rows.keys()):
            for column in before_columns:
                old = before_rows[row_id][column]
                new = after_rows[row_id][column]
                if old != new:
                    differences.append(
                        f"{table} {row_id}: {column} changed "
                        f"from {old!r} to {new!r}"
                    )

    return differences


# The tables the seed creates rows in, which migration 0005 reads or
# changes. A rehearsal that compares empty tables passes by construction.
REQUIRED_SEED_TABLES = (
    "public.nodes",
    "public.workers",
    "public.jobs",
    "public.leases",
)


def empty_seed_tables(snapshot: Mapping[str, str]) -> list[str]:
    """
    One line for each required table that is missing from the snapshot
    or holds no rows, in the order of REQUIRED_SEED_TABLES. An empty
    list means the seed put data where the upgrade will look for it.
    """
    problems: list[str] = []
    for table in REQUIRED_SEED_TABLES:
        if table not in snapshot:
            problems.append(f"{table}: not in the snapshot")
            continue
        _, rows = _read(table, snapshot[table])
        if not rows:
            problems.append(f"{table}: has no rows")
    return problems


REPO_ROOT = Path(__file__).resolve().parents[1]

# What a cleanup step can raise when its command cannot run at all: a
# missing binary, a timeout. A command that runs and fails is not one.
_STEP_FAILURES = (OSError, subprocess.SubprocessError)


def render_override(
    *,
    secret_file: Path,
    tag_prefix: str,
) -> str:
    """
    The compose override of one rehearsal run. It moves the published
    ports off the ones a developer's own stack uses, names the image of
    each side so two releases can be built side by side, and points the
    database secret at a file made for this run.
    """
    image = f"neuromesh-app:{tag_prefix}-${{REHEARSAL_SIDE}}"
    return (
        "services:\n"
        "  postgres:\n"
        "    ports: !override\n"
        '      - "127.0.0.1::5432"\n'
        "  neuromesh:\n"
        f"    image: {image}\n"
        "    ports: !override\n"
        '      - "127.0.0.1::8000"\n'
        "  migrate:\n"
        f"    image: {image}\n"
        "secrets:\n"
        "  postgres_password:\n"
        f"    file: {json.dumps(str(secret_file))}\n"
    )


# Seconds a command may run before it is stopped. A command that is
# stuck, such as a download on a bad connection, must not hold the
# run for as long as the caller is willing to wait. The build limit is
# a ceiling, not a measurement: no good build has been timed yet.
DEFAULT_COMMAND_TIMEOUT = 120.0
BUILD_TIMEOUT = 600.0


def stage(message: str) -> None:
    """Say on stderr which step starts, so silence never means unknown."""
    clock = time.strftime("%H:%M:%S")
    sys.stderr.write(f"{clock} ==> {message}\n")


def _run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
    timeout: float = DEFAULT_COMMAND_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            env=None if env is None else dict(env),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        sys.stderr.write(
            f"$ {' '.join(command)}\ntimed out after {timeout:g}s\n"
        )
        raise
    if check and result.returncode != 0:
        sys.stderr.write(
            f"$ {' '.join(command)}\n{result.stdout}{result.stderr}"
        )
        raise subprocess.CalledProcessError(
            result.returncode,
            list(command),
            result.stdout,
            result.stderr,
        )
    return result


_PUBLISHED_PORT = re.compile(r":(\d+)$")


def parse_published_port(output: str) -> int:
    """
    The host port in the output of docker compose port, which prints an
    address and a port, such as 127.0.0.1:49153 or [::]:49153.
    """
    match = _PUBLISHED_PORT.search(output.strip())
    if match is None:
        raise ValueError(f"no published port in {output!r}")
    return int(match.group(1))


def wait_until(
    check: Callable[[], bool],
    *,
    timeout: float,
    interval: float,
    describe: str,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """
    Call check until it returns true. The check runs once more when the
    deadline is reached, so an answer that arrives during the last sleep
    is not missed, and the last sleep is cut to what is left. An error
    raised by the check is not retried: a command that cannot run is not
    the same as a condition that is not true yet.
    """
    deadline = clock() + timeout
    while not check():
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError(
                f"timed out after {timeout}s waiting for {describe}"
            )
        sleep(min(interval, remaining))


KEY_MARKER = "REHEARSAL_API_KEY="

# Run inside the old release's image, which ships the app package and
# not scripts/issue_api_key.py. The key is printed last, on one marked
# line, so log lines before it cannot be mistaken for it.
ISSUE_KEY_SNIPPET = f"""\
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.presentation.dependencies import get_create_api_key_service

issued = get_create_api_key_service().execute(
    label="upgrade-rehearsal",
    tenant_id=DEFAULT_TENANT_ID,
)
print("{KEY_MARKER}" + issued.plaintext_key)
"""


def parse_issued_key(output: str) -> str:
    """
    The key printed by ISSUE_KEY_SNIPPET. The errors never repeat the
    output, because it may hold a key.
    """
    keys = [
        line.removeprefix(KEY_MARKER)
        for line in output.splitlines()
        if line.startswith(KEY_MARKER)
    ]
    if not keys:
        raise ValueError("no issued key in the output")
    if len(keys) > 1:
        raise ValueError("more than one issued key in the output")
    key = keys[0]
    if key != key.strip() or len(key.split()) != 1:
        raise ValueError("the issued key is empty or contains whitespace")
    return key


NODE_PAYLOAD: Mapping[str, object] = {
    "cpu_cores": 4,
    "memory_mib": 8192,
    "vram_mib": 0,
    "name": "upgrade-rehearsal-node",
}

# A job with no command, so it needs no scope and nothing runs it.
JOB_PAYLOAD: Mapping[str, object] = {
    "cpu_cores": 1,
    "memory_mib": 512,
    "vram_mib": 0,
}

# An agent manages the worker, so the in-process tick never executes
# the job. The scheduler still assigns it and takes the lease, and
# nothing renews that lease, which is why the stack is frozen at once.
WORKER_MANAGED_BY = "AGENT"

Post = Callable[[str, Mapping[str, object]], tuple[int, str]]


@dataclass(frozen=True)
class SeedIds:
    node: str
    worker: str
    job: str


def _created_id(path: str, response: tuple[int, str]) -> str:
    status, body = response
    if status != 201:
        raise ValueError(f"POST {path} returned {status}: {body[:200]}")
    created = json.loads(body)
    identifier = created.get("id") if isinstance(created, dict) else None
    if not isinstance(identifier, str) or not identifier:
        raise ValueError(f"POST {path} returned no id")
    return identifier


def seed_cluster(post: Post) -> SeedIds:
    """
    One node, one worker on it and one job, through the API of the old
    release, so each row is written by that release's own code. post
    takes a path and a payload and returns a status and a body.
    """
    node = _created_id("/nodes", post("/nodes", NODE_PAYLOAD))
    worker = _created_id(
        "/workers",
        post("/workers", {"node_id": node, "managed_by": WORKER_MANAGED_BY}),
    )
    job = _created_id("/jobs", post("/jobs", JOB_PAYLOAD))
    return SeedIds(node=node, worker=worker, job=job)


Compose = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def issue_key(compose: Compose) -> str:
    """
    Issue a key inside the old release's own service, so the database
    URL, the backend and the secret are the ones the release runs with.
    A failure reports the exit code and stderr and never stdout, because
    stdout is where the key is printed.
    """
    result = compose(
        [
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "neuromesh",
            "python",
            "-c",
            ISSUE_KEY_SNIPPET,
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"issuing the key failed with exit code {result.returncode}: "
            f"{result.stderr.strip()[-500:]}"
        )
    return parse_issued_key(result.stdout)


def http_post(base_url: str, key: str) -> Post:
    """
    A post function for seed_cluster that sends the key as a bearer
    token. The key is only ever sent to http://127.0.0.1:<port>, checked
    on the parsed URL so a userinfo trick cannot point it elsewhere.
    """
    parts = urllib.parse.urlsplit(base_url)
    if not (
        parts.scheme == "http"
        and parts.hostname == "127.0.0.1"
        and parts.port is not None
        and parts.netloc == f"127.0.0.1:{parts.port}"
        and parts.path in ("", "/")
        and not parts.query
        and not parts.fragment
    ):
        raise ValueError("the key is only sent to the loopback address")
    base = f"http://{parts.netloc}"

    def post(path: str, payload: Mapping[str, object]) -> tuple[int, str]:
        request = urllib.request.Request(
            base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return int(response.status), response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read().decode("utf-8")

    return post


# Assignment saves the lease first and the worker after it. The seed is
# at rest only when both exist, so stopping the API cannot cut it
# between the two writes.
ASSIGNMENT_SQL = (
    "SELECT (SELECT count(*) FROM leases), "
    "(SELECT count(*) FROM workers WHERE running_job_id IS NOT NULL)"
)


def parse_assignment_state(output: str) -> bool:
    """
    True when a lease exists and a worker holds a job, from the output
    of ASSIGNMENT_SQL run through psql with unaligned, tuples only
    output. Anything that is not two counts is an error, not false, so
    a broken query ends the wait at once and does not poll to the limit.
    """
    parts = output.strip().split("|")
    if len(parts) != 2 or not all(part.isdecimal() for part in parts):
        raise ValueError("unexpected assignment state from the database")
    leases, busy_workers = (int(part) for part in parts)
    return leases > 0 and busy_workers > 0


def require_clean_exit(state: str) -> None:
    """
    Check the state of the stopped API, from docker inspect with the
    format status then exit code. Only a clean exit means the last tick
    finished its writes. 137 means the stop timeout expired and the
    container was killed, possibly in the middle of one.
    """
    parts = state.split()
    if len(parts) != 2 or not parts[1].isdecimal():
        raise ValueError("unexpected container state from docker")
    status, code = parts[0], int(parts[1])
    if status != "exited":
        raise RuntimeError(f"the API did not stop: its status is {status}")
    if code == 137:
        raise RuntimeError("the API was killed (exit code 137), not stopped")
    if code != 0:
        raise RuntimeError(f"the API exited with code {code}")


# The lease lasts 30 seconds, so the wait stays under it: past that,
# what the seed holds may already be expiring.
AT_REST_TIMEOUT = 25.0
AT_REST_INTERVAL = 0.25

_PSQL = ["exec", "-T", "postgres", "psql", "-U", "neuromesh", "-d", "neuromesh"]


def _psql(compose: Compose, sql: str, what: str) -> str:
    """
    Run one statement in the database container and return its output.
    A failure reports the exit code and the end of stderr, never stdout,
    because stdout is table data.
    """
    result = compose([*_PSQL, "-At", "-c", sql])
    if result.returncode != 0:
        raise RuntimeError(
            f"{what} failed with exit code {result.returncode}: "
            f"{result.stderr.strip()[-500:]}"
        )
    return result.stdout


def at_rest(
    compose: Compose,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """
    Wait until the seeded cluster holds a lease and a busy worker. A
    statement that cannot run ends the wait at once: it is an error, not
    a condition that is not true yet.
    """
    wait_until(
        lambda: parse_assignment_state(
            _psql(compose, ASSIGNMENT_SQL, "the assignment query")
        ),
        timeout=AT_REST_TIMEOUT,
        interval=AT_REST_INTERVAL,
        describe="the seeded cluster to hold a lease and a busy worker",
        clock=clock,
        sleep=sleep,
    )


def stop_old_api(
    compose: Compose,
    inspect: Callable[[str], str],
) -> None:
    """
    Stop the API of the old release and check how it ended. inspect
    takes a container id and returns its status and exit code.
    """
    stopped = compose(["stop", "neuromesh"])
    if stopped.returncode != 0:
        raise RuntimeError(
            f"stopping the API failed with exit code {stopped.returncode}: "
            f"{stopped.stderr.strip()[-500:]}"
        )
    listed = compose(["ps", "-aq", "neuromesh"])
    ids = listed.stdout.split()
    if listed.returncode != 0 or len(ids) != 1:
        raise RuntimeError("expected exactly one API container to inspect")
    require_clean_exit(inspect(ids[0]))


def snapshot(compose: Compose) -> Snapshot:
    """Every table of the database exported as CSV, by table name."""
    tables = _psql(compose, TABLES_SQL, "listing the tables").split("\n")
    return {
        table: _psql(compose, copy_sql(table), f"exporting {table}")
        for table in tables
        if table
    }


MIGRATION_COLUMNS = ["version", "name", "checksum"]
MIGRATIONS_SQL = (
    "COPY (SELECT version, name, checksum FROM schema_migrations "
    "ORDER BY version) TO STDOUT "
    f"WITH (FORMAT csv, HEADER, NULL '{NULL_MARKER}')"
)


def read_migrations(text: str) -> Migrations:
    """
    The rows of an export of schema_migrations, by version. The export
    must hold exactly the columns the comparison reads.
    """
    columns, rows = _read("schema_migrations", text)
    if columns != MIGRATION_COLUMNS:
        raise ValueError(
            f"schema_migrations: expected the columns {MIGRATION_COLUMNS}, "
            f"got {columns}"
        )
    return rows


def added_migrations(before: Migrations, after: Migrations) -> list[str]:
    """The versions the upgrade added, in numeric order, with their names."""
    return [
        f"{version} {after[version]['name']}"
        for version in sorted(after.keys() - before.keys(), key=int)
    ]


def compare_migrations(before: Migrations, after: Migrations) -> list[str]:
    """
    Return one line per problem: a version applied before the upgrade
    that is missing afterwards, a name or checksum that changed, and an
    upgrade that applied nothing. An empty list means none.
    """
    problems: list[str] = []
    for version in sorted(before, key=int):
        old = before[version]
        new = after.get(version)
        if new is None:
            problems.append(
                f"schema_migrations {version}: applied before the upgrade "
                "and missing after it"
            )
            continue
        for column in ("name", "checksum"):
            if old[column] != new[column]:
                problems.append(
                    f"schema_migrations {version}: {column} changed "
                    f"from {old[column]!r} to {new[column]!r}"
                )
    if not added_migrations(before, after):
        problems.append("the upgrade applied no migration")
    return problems


def applied_migrations(compose: Compose) -> Migrations:
    """The migrations the database has recorded, by version."""
    return read_migrations(
        _psql(compose, MIGRATIONS_SQL, "reading schema_migrations")
    )


UPGRADED_DATABASE = "neuromesh"
FRESH_DATABASE = "schema_fresh"
FRESH_URL = f"postgresql://neuromesh@postgres:5432/{FRESH_DATABASE}"
_PG_DUMP = ["exec", "-T", "postgres", "pg_dump", "-U", "neuromesh"]
# The two commands pg_dump writes with a random key and nothing else.
_RANDOM_KEY_LINES = ("\\restrict ", "\\unrestrict ")


def schema_lines(dump: str) -> list[str]:
    """
    The lines of a pg_dump schema without the two commands that carry
    a random key, which differ between any two dumps.
    """
    return [
        line
        for line in dump.splitlines()
        if not line.startswith(_RANDOM_KEY_LINES)
    ]


def compare_schemas(upgraded: str, fresh: str) -> list[str]:
    """
    Return one line per problem: a dump with no CREATE TABLE line, then
    every line that is in one schema and not in the other, upgraded side
    first. The comparison is line by line and in order. An empty list
    means the two match.
    """
    upgraded_lines = schema_lines(upgraded)
    fresh_lines = schema_lines(fresh)

    problems: list[str] = []
    for name, lines in (("upgraded", upgraded_lines), ("fresh", fresh_lines)):
        if not any(line.startswith("CREATE TABLE ") for line in lines):
            problems.append(f"the {name} schema has no CREATE TABLE line")

    matcher = difflib.SequenceMatcher(
        None, upgraded_lines, fresh_lines, autojunk=False
    )
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        problems.extend(
            f"only in the upgraded schema: {line}"
            for line in upgraded_lines[a1:a2]
        )
        problems.extend(
            f"only in the fresh schema: {line}" for line in fresh_lines[b1:b2]
        )
    return problems


def schema_dump(compose: Compose, database: str) -> str:
    """
    The schema of one database as pg_dump writes it, without data and
    without owners. A failure reports the exit code and the end of
    stderr, never stdout.
    """
    result = compose(
        [*_PG_DUMP, "-d", database, "--schema-only", "--no-owner"]
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"dumping the schema of {database} failed with exit code "
            f"{result.returncode}: {result.stderr.strip()[-500:]}"
        )
    return result.stdout


def fresh_schema(old: Compose, new: Compose) -> str:
    """
    Build a database from nothing with the new release's migrate service
    and return its schema. The database is made in the Postgres of the
    run, which the teardown removes with its volume.
    """
    _psql(
        old,
        f"CREATE DATABASE {FRESH_DATABASE}",
        "creating the fresh database",
    )
    new(
        [
            "run",
            "--rm",
            "--no-deps",
            "-e",
            f"NEUROMESH_DATABASE_URL={FRESH_URL}",
            "migrate",
        ]
    )
    return schema_dump(old, FRESH_DATABASE)


def docker_inspect(container_id: str) -> str:
    """The status and exit code of a container, as require_clean_exit reads them."""
    return _run(
        [
            "docker",
            "inspect",
            "--format",
            "{{.State.Status}} {{.State.ExitCode}}",
            container_id,
        ]
    ).stdout


def _resolve(ref: str) -> str:
    result = _run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=REPO_ROOT,
        check=False,
    )
    sha = result.stdout.strip()
    if result.returncode != 0 or not sha:
        raise SystemExit(f"cannot resolve {ref!r} to a commit")
    return sha


def _archive(sha: str) -> bytes:
    """The tree of a commit as tar bytes, from git archive."""
    result = subprocess.run(
        ["git", "archive", "--format=tar", sha],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise SystemExit(f"git archive failed for {sha}: {detail}")
    return result.stdout


def _export(sha: str, destination: Path) -> None:
    """
    Write the tree of a commit into destination. A worktree would
    register itself in the repository's own metadata, and a run that
    died would leave that registration to prune. An export leaves
    nothing there, and no .git entry in the Docker build context.
    """
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(_archive(sha)), mode="r:") as tar:
        tar.extractall(destination, filter="data")


def _leftovers(project: str, tag_prefix: str, root: Path) -> list[str]:
    """
    What a run left on the machine, looked up by the names it used. A
    lookup that fails is reported too, because a silent failure would
    read as a clean teardown.
    """
    label = f"label=com.docker.compose.project={project}"
    queries = (
        ("containers", ["docker", "ps", "-aq", "--filter", label]),
        ("volumes", ["docker", "volume", "ls", "-q", "--filter", label]),
        (
            "images",
            [
                "docker",
                "image",
                "ls",
                "-q",
                "--filter",
                f"reference=neuromesh-app:{tag_prefix}-*",
            ],
        ),
    )
    found: list[str] = []

    for name, command in queries:
        try:
            result = _run(command, check=False)
        except _STEP_FAILURES:
            found.append(f"{name} (could not be listed)")
            continue
        if result.returncode != 0:
            found.append(f"{name} (could not be listed)")
        elif result.stdout.split():
            found.append(f"{len(result.stdout.split())} {name}")

    if root.exists():
        found.append(f"the directory {root}")

    return found


@contextlib.contextmanager
def _terminate_as_exit() -> Iterator[None]:
    """
    Turn SIGTERM and SIGHUP into SystemExit, so the cleanup of a run
    that is stopped from outside still happens. A second signal while
    the cleanup runs is ignored. Handlers can only be set from the main
    thread, so elsewhere this does nothing.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    fired = False

    def handler(signum: int, frame: FrameType | None) -> None:
        nonlocal fired
        if not fired:
            fired = True
            raise SystemExit(128 + signum)

    previous: dict[signal.Signals, Any] = {}
    for number in (signal.SIGTERM, signal.SIGHUP):
        previous[number] = signal.signal(number, handler)

    try:
        yield
    finally:
        for number, original in previous.items():
            signal.signal(number, original)


@dataclass(frozen=True)
class Environment:
    root: Path
    old_dir: Path
    new_dir: Path
    project: str
    override: Path
    tag_prefix: str

    def compose(
        self,
        side: str,
        *args: str,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        directory = self.old_dir if side == "old" else self.new_dir
        return _run(
            [
                "docker",
                "compose",
                "-p",
                self.project,
                "--project-directory",
                str(directory),
                "-f",
                str(directory / "docker-compose.yml"),
                "-f",
                str(self.override),
                *args,
            ],
            env={**os.environ, "REHEARSAL_SIDE": side},
            check=check,
            timeout=(
                DEFAULT_COMMAND_TIMEOUT if timeout is None else timeout
            ),
        )


def _teardown(environment: Environment) -> None:
    """
    Stop what the run started and remove the images it built. Each
    step is tried on its own, so one that cannot run (no docker, a
    daemon that is down) does not stop the others. What this misses
    is found by _leftovers, which the caller checks afterwards.
    """
    with contextlib.suppress(*_STEP_FAILURES):
        environment.compose(
            "old", "down", "-v", "--remove-orphans", check=False
        )
    for side in ("old", "new"):
        with contextlib.suppress(*_STEP_FAILURES):
            _run(
                [
                    "docker",
                    "image",
                    "rm",
                    "-f",
                    f"neuromesh-app:{environment.tag_prefix}-{side}",
                ],
                check=False,
            )


@contextlib.contextmanager
def rehearsal_environment(
    old_ref: str,
    new_ref: str,
) -> Iterator[Environment]:
    """
    The environment of one rehearsal, torn down on exit however the run
    ends. SIGTERM and SIGHUP end it through SystemExit, so the cleanup
    runs. SIGKILL cannot be handled, and what it leaves is found by the
    prefixes upgrade-rehearsal- (directories, containers, volumes) and
    neuromesh-app:rehearsal- (images).
    """
    with _terminate_as_exit(), _environment(old_ref, new_ref) as environment:
        yield environment


@contextlib.contextmanager
def _environment(
    old_ref: str,
    new_ref: str,
) -> Iterator[Environment]:
    """
    The two releases exported with git archive, a secret made for this
    run, free ports and an override file, all under one temporary
    directory. Everything is removed on exit and the result is checked:
    what is left behind is reported, and ends a run that was otherwise
    fine.
    """
    old_sha = _resolve(old_ref)
    new_sha = _resolve(new_ref)
    run_id = uuid.uuid4().hex[:8]
    root = Path(tempfile.mkdtemp(prefix="upgrade-rehearsal-"))
    environment: Environment | None = None
    failed = True

    try:
        old_dir = root / "old"
        new_dir = root / "new"
        _export(old_sha, old_dir)
        _export(new_sha, new_dir)

        # A throwaway secret for an ephemeral database in a temporary
        # directory. Mode 0644 lets the container user read it without
        # a chown, so the run needs no sudo.
        secret = root / "postgres_password"
        secret.write_text(secrets.token_hex(24))
        secret.chmod(0o644)

        tag_prefix = f"rehearsal-{run_id}"
        override = root / "override.yml"
        override.write_text(
            render_override(
                secret_file=secret,
                tag_prefix=tag_prefix,
            )
        )
        environment = Environment(
            root=root,
            old_dir=old_dir,
            new_dir=new_dir,
            project=f"upgrade-rehearsal-{run_id}",
            override=override,
            tag_prefix=tag_prefix,
        )
        yield environment
        failed = False
    finally:
        if environment is not None:
            _teardown(environment)
        shutil.rmtree(root, ignore_errors=True)
        if environment is not None:
            remaining = _leftovers(
                environment.project, environment.tag_prefix, root
            )
        else:
            remaining = [f"the directory {root}"] if root.exists() else []
        if remaining:
            message = "the rehearsal left behind " + ", ".join(remaining)
            if failed:
                sys.stderr.write(message + "\n")
            else:
                raise SystemExit(message)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rehearse an upgrade between two releases."
    )
    parser.add_argument(
        "--old", required=True, help="the release the database is seeded with"
    )
    parser.add_argument(
        "--new",
        default="HEAD",
        help="the commit whose migrations upgrade it",
    )
    args = parser.parse_args(argv)

    stage("preparing the two releases")
    with rehearsal_environment(args.old, args.new) as environment:
        stage(
            "building and starting the old release "
            f"(limit {BUILD_TIMEOUT:g}s)"
        )
        environment.compose(
            "old",
            "up",
            "-d",
            "--build",
            "--wait",
            "--wait-timeout",
            "180",
            timeout=BUILD_TIMEOUT,
        )
        api_port = parse_published_port(
            environment.compose("old", "port", "neuromesh", "8000").stdout
        )
        stage("issuing the API key")
        key = issue_key(
            lambda arguments: environment.compose(
                "old", *arguments, check=False
            )
        )
        stage("seeding the cluster through the API")
        ids = seed_cluster(http_post(f"http://127.0.0.1:{api_port}", key))
        print(f"seeded node {ids.node}, worker {ids.worker}, job {ids.job}")

        def old_compose(
            arguments: Sequence[str],
        ) -> subprocess.CompletedProcess[str]:
            return environment.compose("old", *arguments, check=False)

        stage("waiting for the seeded cluster to settle")
        at_rest(old_compose)
        stage("stopping the old API")
        stop_old_api(old_compose, docker_inspect)
        stage("exporting the tables before the upgrade")
        before = snapshot(old_compose)
        stage("checking that the seed left data in every required table")
        problems = empty_seed_tables(before)
        if problems:
            raise RuntimeError("the seed is not usable: " + "; ".join(problems))
        print(f"exported {len(before)} tables before the upgrade")
        migrations_before = applied_migrations(old_compose)

        stage(f"building the new release (limit {BUILD_TIMEOUT:g}s)")
        environment.compose(
            "new", "build", "neuromesh", timeout=BUILD_TIMEOUT
        )
        stage("applying the new migrations to the seeded database")
        # Only the one-shot migrate service runs. The new API stays
        # down so nothing writes between the two exports, and
        # --no-deps keeps compose from recreating postgres.
        environment.compose("new", "run", "--rm", "--no-deps", "migrate")
        stage("exporting the tables after the upgrade")
        after = snapshot(old_compose)
        migrations_after = applied_migrations(old_compose)
        stage("comparing the tables before and after the upgrade")
        for added in added_migrations(migrations_before, migrations_after):
            print(f"applied migration {added}")
        migration_problems = compare_migrations(
            migrations_before, migrations_after
        )
        if migration_problems:
            raise RuntimeError(
                "the migrations are not as expected: "
                + "; ".join(migration_problems)
            )
        differences = compare_snapshots(before, after)
        if differences:
            raise RuntimeError(
                "the upgrade changed the database: "
                + "; ".join(differences)
            )
        print(f"the upgrade changed nothing in {len(after)} tables")

        def new_compose(
            arguments: Sequence[str],
        ) -> subprocess.CompletedProcess[str]:
            return environment.compose("new", *arguments)

        stage("building a fresh database with the new migrations")
        fresh = fresh_schema(old_compose, new_compose)
        stage("dumping the schema of the upgraded database")
        upgraded = schema_dump(old_compose, UPGRADED_DATABASE)
        stage("comparing the two schemas")
        schema_problems = compare_schemas(upgraded, fresh)
        if schema_problems:
            raise RuntimeError(
                "the upgraded schema differs from a fresh one: "
                + "; ".join(schema_problems)
            )
        lines = len(schema_lines(upgraded))
        print(f"the upgraded schema matches a fresh one ({lines} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
