from __future__ import annotations

import contextlib
import io
import json
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Sequence
from email.message import Message
from types import SimpleNamespace

import pytest

from scripts import upgrade_rehearsal

Get = Callable[[str], tuple[int, str]]
Compose = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

SEED = upgrade_rehearsal.SeedIds(node="n-1", worker="w-1", job="j-1")
NODE, WORKER, JOB = "/nodes/n-1", "/workers/w-1", "/jobs/j-1"
PREFIX = "the new API did not serve the seeded rows: "

REMOVE = ["rm", "-f", "neuromesh"]
UP = [
    "up",
    "-d",
    "--no-deps",
    "--no-build",
    "--wait",
    "--wait-timeout",
    "90",
    "neuromesh",
]
PORT = ["port", "neuromesh", "8000"]

BAD_URLS = [
    "https://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://user@127.0.0.1:8000",
    "http://127.0.0.1:8000@evil.example:80",
    "http://127.0.0.1:8000/path",
    "http://127.0.0.1:8000?x=1",
    "http://127.0.0.1:8000#f",
]


def completed(
    stdout: str = "", code: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


class FakeResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_a_get_sends_the_key_as_a_bearer_token_to_the_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[urllib.request.Request] = []

    def fake_urlopen(
        request: urllib.request.Request, timeout: float
    ) -> FakeResponse:
        seen.append(request)
        return FakeResponse(200, '{"id": "x"}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    get = upgrade_rehearsal.http_get("http://127.0.0.1:8123", "secret-key")

    assert get("/nodes/n-1") == (200, '{"id": "x"}')
    request = seen[0]
    assert request.get_method() == "GET"
    assert request.full_url == "http://127.0.0.1:8123/nodes/n-1"
    assert request.get_header("Authorization") == "Bearer secret-key"
    assert request.data is None


def test_an_error_status_is_returned_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(
        request: urllib.request.Request, timeout: float
    ) -> FakeResponse:
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            Message(),
            io.BytesIO(b'{"detail": "x"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    get = upgrade_rehearsal.http_get("http://127.0.0.1:8123", "k")

    assert get("/nodes/n-1") == (404, '{"detail": "x"}')


@pytest.mark.parametrize("url", BAD_URLS)
def test_the_key_is_only_sent_to_the_loopback_address(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(request: object, timeout: float) -> object:
        raise AssertionError("a request was sent")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    with pytest.raises(ValueError, match="only sent to the loopback address"):
        upgrade_rehearsal.http_post(url, "k")
    with pytest.raises(ValueError, match="only sent to the loopback address"):
        upgrade_rehearsal.http_get(url, "k")


def test_the_loopback_base_drops_a_trailing_slash() -> None:
    base = "http://127.0.0.1:8000"

    assert upgrade_rehearsal.loopback_base(base) == base
    assert upgrade_rehearsal.loopback_base(base + "/") == base


def ok(identifier: str, **extra: object) -> tuple[int, str]:
    return 200, json.dumps({"id": identifier, **extra})


def holding_the_seeded_job() -> tuple[int, str]:
    command = list(upgrade_rehearsal.JOB_COMMAND)
    return ok("w-1", running_job={"id": "j-1", "command": command})


def served() -> dict[str, tuple[int, str]]:
    return {
        NODE: ok("n-1"),
        WORKER: holding_the_seeded_job(),
        JOB: ok("j-1"),
    }


def getter(
    responses: dict[str, tuple[int, str]],
) -> tuple[Get, list[str]]:
    paths: list[str] = []

    def get(path: str) -> tuple[int, str]:
        paths.append(path)
        return responses[path]

    return get, paths


def test_the_three_rows_are_read_in_order() -> None:
    get, paths = getter(served())

    upgrade_rehearsal.read_back(get, SEED)

    assert paths == [NODE, WORKER, JOB]


def test_a_changed_state_is_not_a_problem() -> None:
    # ADR 0088 decision 6: the new API may change a status on startup.
    # ADR 0089 decision 4 still requires the worker to hold the job.
    responses = served()
    command = list(upgrade_rehearsal.JOB_COMMAND)
    responses[WORKER] = ok(
        "w-1",
        status="OFFLINE",
        running_job={"id": "j-1", "command": command},
    )
    responses[JOB] = ok("j-1", status="QUEUED")
    get, _ = getter(responses)

    upgrade_rehearsal.read_back(get, SEED)


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_a_status_other_than_200_is_named(status: int) -> None:
    responses = served()
    responses[NODE] = (status, "{}")
    get, _ = getter(responses)

    with pytest.raises(RuntimeError) as caught:
        upgrade_rehearsal.read_back(get, SEED)

    assert str(caught.value) == (
        f"{PREFIX}GET {NODE} returned {status}, expected 200"
    )


@pytest.mark.parametrize(
    "body", ["{}", "[]", "null", '{"id": 5}', '{"id": "other"}']
)
def test_a_body_with_a_different_id_is_named(body: str) -> None:
    responses = served()
    responses[JOB] = (200, body)
    get, _ = getter(responses)

    with pytest.raises(RuntimeError) as caught:
        upgrade_rehearsal.read_back(get, SEED)

    assert str(caught.value) == (
        f"{PREFIX}GET {JOB} returned a body with a different id"
    )


def test_a_body_that_is_not_json_is_named() -> None:
    responses = served()
    responses[NODE] = (200, "<html>")
    get, _ = getter(responses)

    with pytest.raises(RuntimeError) as caught:
        upgrade_rehearsal.read_back(get, SEED)

    assert str(caught.value) == (
        f"{PREFIX}GET {NODE} returned a body that is not JSON"
    )


def test_every_problem_is_reported_not_only_the_first() -> None:
    responses = {
        NODE: (404, "{}"),
        WORKER: ok("other"),
        JOB: (200, "nope"),
    }
    get, paths = getter(responses)

    with pytest.raises(RuntimeError) as caught:
        upgrade_rehearsal.read_back(get, SEED)

    assert str(caught.value) == (
        PREFIX
        + f"GET {NODE} returned 404, expected 200; "
        + f"GET {WORKER} returned a body with a different id; "
        + f"GET {JOB} returned a body that is not JSON"
    )
    assert paths == [NODE, WORKER, JOB]


@pytest.mark.parametrize(
    "response",
    [
        (500, '{"secret": "hunter2"}'),
        (200, '{"id": "other", "secret": "hunter2"}'),
    ],
)
def test_a_body_is_never_in_the_message(response: tuple[int, str]) -> None:
    responses = served()
    responses[WORKER] = response
    get, _ = getter(responses)

    with pytest.raises(RuntimeError) as caught:
        upgrade_rehearsal.read_back(get, SEED)

    assert "hunter2" not in str(caught.value)


def test_the_old_container_is_removed_then_the_new_api_started_alone() -> None:
    seen: list[list[str]] = []

    def compose(
        arguments: Sequence[str],
    ) -> subprocess.CompletedProcess[str]:
        seen.append(list(arguments))
        return completed("127.0.0.1:49153\n" if arguments[0] == "port" else "")

    assert upgrade_rehearsal.start_new_api(compose) == 49153
    assert seen == [REMOVE, UP, PORT]


def test_a_failed_removal_never_reaches_the_start() -> None:
    seen: list[list[str]] = []

    def compose(
        arguments: Sequence[str],
    ) -> subprocess.CompletedProcess[str]:
        seen.append(list(arguments))
        return completed("", 1, "in use")

    with pytest.raises(
        RuntimeError,
        match="removing the stopped API container failed with exit code 1: "
        "in use",
    ):
        upgrade_rehearsal.start_new_api(compose)

    assert seen == [REMOVE]


def test_a_failed_start_never_reaches_the_port() -> None:
    seen: list[list[str]] = []

    def compose(
        arguments: Sequence[str],
    ) -> subprocess.CompletedProcess[str]:
        seen.append(list(arguments))
        if arguments[0] == "up":
            return completed("", 1, "container is unhealthy")
        return completed()

    with pytest.raises(
        RuntimeError,
        match="starting the new API failed with exit code 1: "
        "container is unhealthy",
    ):
        upgrade_rehearsal.start_new_api(compose)

    assert seen == [REMOVE, UP]


def test_a_failed_port_lookup_is_reported() -> None:
    def compose(
        arguments: Sequence[str],
    ) -> subprocess.CompletedProcess[str]:
        if arguments[0] == "port":
            return completed("", 1, "no such service")
        return completed()

    with pytest.raises(
        RuntimeError,
        match="finding the port of the new API failed with exit code 1: "
        "no such service",
    ):
        upgrade_rehearsal.start_new_api(compose)


def test_stopping_the_new_api_uses_the_same_stop_and_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, object]] = []
    monkeypatch.setattr(
        upgrade_rehearsal,
        "stop_old_api",
        lambda compose, inspect: calls.append((compose, inspect)),
    )

    def compose(
        arguments: Sequence[str],
    ) -> subprocess.CompletedProcess[str]:
        return completed()

    def inspect(container_id: str) -> str:
        return "exited 0\n"

    upgrade_rehearsal.stop_new_api(compose, inspect)

    assert calls == [(compose, inspect)]


SEEDED = {
    "public.nodes": "id,tenant_id\n1,a\n",
    "public.workers": "id,tenant_id\n1,a\n",
    "public.jobs": "id,tenant_id\n1,a\n",
    "public.leases": "id,tenant_id\n1,a\n",
}
VERSIONS = {"4": {"version": "4", "name": "four", "checksum": "c4"}}
UPGRADED_VERSIONS = {
    **VERSIONS,
    "5": {"version": "5", "name": "five", "checksum": "c5"},
}
SCHEMA = "CREATE TABLE public.nodes (id uuid);"
STARTING = "stage: starting the new API on the upgraded database"


class Recorder:
    def __init__(self, *, fail_up: bool = False) -> None:
        self.events: list[str] = []
        self.gets: list[tuple[str, str]] = []
        self.ids: list[SimpleNamespace] = []
        self.fail_up = fail_up

    def compose(
        self,
        side: str,
        *args: str,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.events.append(f"compose {side} {' '.join(args)}")
        if self.fail_up and side == "new" and args[0] == "up":
            if check:
                raise subprocess.CalledProcessError(
                    1, list(args), "", "container is unhealthy"
                )
            return subprocess.CompletedProcess(
                list(args), 1, "", "container is unhealthy"
            )
        stdout = "127.0.0.1:49153\n" if args[0] == "port" else ""
        return subprocess.CompletedProcess(list(args), 0, stdout, "")


def wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    recorder: Recorder | None = None,
    read: Callable[[object, SimpleNamespace], None] | None = None,
) -> Recorder:
    recorder = recorder or Recorder()
    events = recorder.events
    snapshots = iter([SEEDED, SEEDED])
    versions = iter([VERSIONS, UPGRADED_VERSIONS])

    @contextlib.contextmanager
    def fake_environment(old_ref: str, new_ref: str) -> Iterator[Recorder]:
        yield recorder

    def fake_snapshot(compose: object) -> dict[str, str]:
        events.append("snapshot")
        return next(snapshots)

    def fake_read(get: object, ids: SimpleNamespace) -> None:
        events.append("read_back")
        recorder.ids.append(ids)

    def fake_get(base_url: str, key: str) -> str:
        recorder.gets.append((base_url, key))
        return "get"

    def fake_stop(compose: Compose, inspect: object) -> None:
        # Both the old and the new API are stopped through this, so the
        # side of the compose it is given shows in the events.
        events.append("stop")
        compose(["stop", "neuromesh"])

    patches: dict[str, object] = {
        "rehearsal_environment": fake_environment,
        "issue_key": lambda runner: "k",
        "http_post": lambda base_url, key: "post",
        "seed_cluster": lambda post: SimpleNamespace(
            node="n", worker="w", job="j"
        ),
        "stage": lambda message: events.append(f"stage: {message}"),
        "at_rest": lambda compose: events.append("rest"),
        "stop_old_api": fake_stop,
        "snapshot": fake_snapshot,
        "applied_migrations": lambda compose: next(versions),
        "fresh_schema": lambda old, new: SCHEMA,
        "schema_dump": lambda compose, database: SCHEMA,
    }
    for name, fake in patches.items():
        monkeypatch.setattr(upgrade_rehearsal, name, fake)

    # raising=False lets these tests run, and fail for the right
    # reason, before the functions exist.
    new_api: dict[str, object] = {
        "http_get": fake_get,
        "read_back": read or fake_read,
    }
    for name, fake in new_api.items():
        monkeypatch.setattr(upgrade_rehearsal, name, fake, raising=False)
    return recorder


def test_the_new_api_is_checked_after_the_schemas_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = wire(monkeypatch)

    assert upgrade_rehearsal.main(["--old", "v0.6.0"]) == 0

    order = [
        "stage: comparing the two schemas",
        STARTING,
        f"compose new {' '.join(UP)}",
        "stage: reading back the seeded rows through the new API",
        "read_back",
        "stage: stopping the new API",
        "compose new stop neuromesh",
    ]
    positions = [recorder.events.index(item) for item in order]
    assert positions == sorted(positions)


def test_the_new_api_is_removed_started_and_stopped_on_the_new_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = wire(monkeypatch)

    assert upgrade_rehearsal.main(["--old", "v0.6.0"]) == 0

    events = recorder.events
    after = events[events.index(STARTING) :]
    assert [e for e in after if e.startswith("compose ")] == [
        f"compose new {' '.join(REMOVE)}",
        f"compose new {' '.join(UP)}",
        f"compose new {' '.join(PORT)}",
        "compose new stop neuromesh",
    ]


def test_the_old_key_is_sent_to_the_started_port_and_the_seed_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = wire(monkeypatch)

    assert upgrade_rehearsal.main(["--old", "v0.6.0"]) == 0

    assert recorder.gets == [("http://127.0.0.1:49153", "k")]
    assert [(i.node, i.worker, i.job) for i in recorder.ids] == [
        ("n", "w", "j")
    ]


def test_a_success_prints_what_was_served(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wire(monkeypatch)

    assert upgrade_rehearsal.main(["--old", "v0.6.0"]) == 0

    assert (
        "the new API served the seeded node, worker and job"
        in capsys.readouterr().out
    )


def test_a_failed_read_ends_the_run_with_its_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_read(get: object, ids: SimpleNamespace) -> None:
        raise RuntimeError(PREFIX + "GET /jobs/j returned 404, expected 200")

    wire(monkeypatch, read=failing_read)

    with pytest.raises(RuntimeError, match="returned 404, expected 200"):
        upgrade_rehearsal.main(["--old", "v0.6.0"])


def test_a_failed_start_never_reaches_the_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = wire(monkeypatch, recorder=Recorder(fail_up=True))

    with pytest.raises(
        RuntimeError,
        match="starting the new API failed with exit code 1: "
        "container is unhealthy",
    ):
        upgrade_rehearsal.main(["--old", "v0.6.0"])

    assert "read_back" not in recorder.events


MALFORMED_PORT_URLS = [
    "http://127.0.0.1:abc",
    "http://127.0.0.1:99999",
    "http://127.0.0.1:80 ",
    "http://127.0.0.1:8000 ",
    "http://127.0.0.1: ",
]


@pytest.mark.parametrize("url", MALFORMED_PORT_URLS)
def test_a_malformed_port_is_refused_with_the_same_message(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(request: object, timeout: float) -> object:
        raise AssertionError("a request was sent")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    with pytest.raises(ValueError, match="only sent to the loopback address"):
        upgrade_rehearsal.loopback_base(url)
    with pytest.raises(ValueError, match="only sent to the loopback address"):
        upgrade_rehearsal.http_post(url, "k")
    with pytest.raises(ValueError, match="only sent to the loopback address"):
        upgrade_rehearsal.http_get(url, "k")
