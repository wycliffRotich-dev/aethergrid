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
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any

Snapshot = dict[str, str]

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


def _run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(command),
        cwd=cwd,
        env=None if env is None else dict(env),
        text=True,
        capture_output=True,
        check=False,
    )
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

    with rehearsal_environment(args.old, args.new) as environment:
        config = environment.compose("old", "config").stdout
        for line in config.splitlines():
            if any(
                key in line
                for key in ("name:", "image:", "published:", "file:", "context:")
            ):
                print(line)
        print(f"environment ready: project {environment.project}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
