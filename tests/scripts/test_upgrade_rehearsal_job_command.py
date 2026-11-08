from __future__ import annotations

import json
from collections.abc import Callable, Mapping

import pytest

from app.domain.value_objects.api_key_scope import JOBS_EXECUTE
from scripts import upgrade_rehearsal

# ADR 0089: the rehearsal seeds a job with a command, issues its key with
# the jobs:execute scope inside the old release, and checks the command
# the worker route returns after the upgrade.

Get = Callable[[str], tuple[int, str]]

SEED = upgrade_rehearsal.SeedIds(node="n-1", worker="w-1", job="j-1")
NODE, WORKER, JOB = "/nodes/n-1", "/workers/w-1", "/jobs/j-1"
PREFIX = "the new API did not serve the seeded rows: "
NO_RUNNING_JOB = f"GET {WORKER} returned no running job"
DIFFERENT_COMMAND = (
    f"GET {WORKER} returned a running job with a different command"
)


class RecordingPost:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def __call__(
        self,
        path: str,
        payload: Mapping[str, object],
    ) -> tuple[int, str]:
        self.calls.append((path, payload))
        return 201, json.dumps({"id": f"{path.strip('/')}-id"})


def ok(identifier: str, **extra: object) -> tuple[int, str]:
    return 200, json.dumps({"id": identifier, **extra})


def seeded_command() -> list[str]:
    return list(upgrade_rehearsal.JOB_COMMAND)


def worker_holding(command: object) -> tuple[int, str]:
    return ok("w-1", running_job={"id": "j-1", "command": command})


def served(worker: tuple[int, str]) -> dict[str, tuple[int, str]]:
    return {NODE: ok("n-1"), WORKER: worker, JOB: ok("j-1")}


def getter(responses: Mapping[str, tuple[int, str]]) -> Get:
    def get(path: str) -> tuple[int, str]:
        return responses[path]

    return get


def test_the_seeded_command_is_a_list_of_non_empty_strings() -> None:
    command = seeded_command()

    assert len(command) > 0
    assert all(isinstance(part, str) and part for part in command)


def test_the_job_is_seeded_with_that_command() -> None:
    post = RecordingPost()

    upgrade_rehearsal.seed_cluster(post)

    path, payload = post.calls[2]
    assert path == "/jobs"
    assert payload["command"] == seeded_command()


def test_the_snippet_issues_the_key_with_the_execute_scope() -> None:
    snippet = upgrade_rehearsal.ISSUE_KEY_SNIPPET

    assert f'scopes=frozenset({{"{JOBS_EXECUTE}"}})' in snippet


def test_the_snippet_does_not_import_the_scope_name() -> None:
    # The snippet runs in the old release, which may not have the module
    # (ADR 0089 decision 1). The string above is pinned to the constant
    # on main by the previous test.
    snippet = upgrade_rehearsal.ISSUE_KEY_SNIPPET

    assert "api_key_scope" not in snippet
    assert "JOBS_EXECUTE" not in snippet


def test_a_worker_holding_the_seeded_command_passes() -> None:
    get = getter(served(worker_holding(seeded_command())))

    upgrade_rehearsal.read_back(get, SEED)


@pytest.mark.parametrize("command", [["other"], [], None])
def test_a_different_command_is_named(command: object) -> None:
    get = getter(served(worker_holding(command)))

    with pytest.raises(RuntimeError) as caught:
        upgrade_rehearsal.read_back(get, SEED)

    assert str(caught.value) == PREFIX + DIFFERENT_COMMAND


def test_the_command_as_one_string_is_a_different_command() -> None:
    get = getter(served(worker_holding(" ".join(seeded_command()))))

    with pytest.raises(RuntimeError) as caught:
        upgrade_rehearsal.read_back(get, SEED)

    assert str(caught.value) == PREFIX + DIFFERENT_COMMAND


def test_a_running_job_without_a_command_is_a_different_command() -> None:
    worker = ok("w-1", running_job={"id": "j-1"})
    get = getter(served(worker))

    with pytest.raises(RuntimeError) as caught:
        upgrade_rehearsal.read_back(get, SEED)

    assert str(caught.value) == PREFIX + DIFFERENT_COMMAND


@pytest.mark.parametrize("extra", [{}, {"running_job": None}])
def test_a_worker_without_a_running_job_is_named(
    extra: Mapping[str, object],
) -> None:
    get = getter(served(ok("w-1", **extra)))

    with pytest.raises(RuntimeError) as caught:
        upgrade_rehearsal.read_back(get, SEED)

    assert str(caught.value) == PREFIX + NO_RUNNING_JOB


def test_the_command_problem_is_reported_with_the_other_problems() -> None:
    responses = {
        NODE: (404, "{}"),
        WORKER: worker_holding(["other"]),
        JOB: ok("j-1"),
    }

    with pytest.raises(RuntimeError) as caught:
        upgrade_rehearsal.read_back(getter(responses), SEED)

    assert str(caught.value) == (
        PREFIX
        + f"GET {NODE} returned 404, expected 200; "
        + DIFFERENT_COMMAND
    )


def test_a_command_is_never_in_the_message() -> None:
    secret = "hunter2"
    get = getter(served(worker_holding(["run", secret])))

    with pytest.raises(RuntimeError) as caught:
        upgrade_rehearsal.read_back(get, SEED)

    message = str(caught.value)
    assert secret not in message
    assert " ".join(seeded_command()) not in message
