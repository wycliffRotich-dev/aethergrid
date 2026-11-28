from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence

import pytest

from scripts import upgrade_rehearsal

# ADR 0111: a worker that holds nothing after the new API starts is
# accepted when the database holds a reclaim record for the seeded job
# and worker. Every other worker body still ends the run.

Get = Callable[[str], tuple[int, str]]
Compose = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

SEED = upgrade_rehearsal.SeedIds(node="n-1", worker="w-1", job="j-1")
NODE, WORKER, JOB = "/nodes/n-1", "/workers/w-1", "/jobs/j-1"
PREFIX = "the new API did not serve the seeded rows: "
NO_RECORD = f"GET {WORKER} returned no running job and no reclaim record"
DIFFERENT_COMMAND = (
    f"GET {WORKER} returned a running job with a different command"
)

JOB_ID = "6f1c1d3e-8a52-4d0b-9a57-0c2b7f3e9a11"
WORKER_ID = "b7d2a9c4-35e1-4f6a-8c0d-1e9f2a4b6c70"
EXPECTED_SQL = (
    "SELECT count(*) FROM lease_reclaims "
    f"WHERE job_id = '{JOB_ID}' AND worker_id = '{WORKER_ID}'"
)


def ids(
    *, worker: str = WORKER_ID, job: str = JOB_ID
) -> upgrade_rehearsal.SeedIds:
    return upgrade_rehearsal.SeedIds(node="n-1", worker=worker, job=job)


def completed(
    stdout: str = "", code: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


def ok(identifier: str, **extra: object) -> tuple[int, str]:
    return 200, json.dumps({"id": identifier, **extra})


def worker_holding(command: object) -> tuple[int, str]:
    return ok("w-1", running_job={"id": "j-1", "command": command})


def idle_worker() -> tuple[int, str]:
    return ok("w-1", status="IDLE")


def served(worker: tuple[int, str]) -> dict[str, tuple[int, str]]:
    return {NODE: ok("n-1"), WORKER: worker, JOB: ok("j-1")}


def getter(responses: Mapping[str, tuple[int, str]]) -> Get:
    def get(path: str) -> tuple[int, str]:
        return responses[path]

    return get


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def never() -> bool:
    raise AssertionError("the reclaim record was asked for")


def read(
    responses: Mapping[str, tuple[int, str]],
    reclaimed: Callable[[], bool],
    fake: FakeTime,
) -> None:
    upgrade_rehearsal.read_back(
        getter(responses),
        SEED,
        reclaimed=reclaimed,
        clock=fake.clock,
        sleep=fake.sleep,
    )


def test_the_reclaim_query_counts_the_rows_of_the_job_and_worker() -> None:
    assert upgrade_rehearsal.reclaim_sql(ids()) == EXPECTED_SQL


@pytest.mark.parametrize(
    "bad", ["j-1", "", "x' OR '1'='1", "6f1c1d3e-8a52-4d0b-9a57-0c2b7f3e9a1g"]
)
@pytest.mark.parametrize("field", ["job", "worker"])
def test_an_id_that_is_not_a_uuid_is_refused(field: str, bad: str) -> None:
    seed = ids(**{field: bad})

    with pytest.raises(
        ValueError, match=f"^the seeded {field} id is not a UUID$"
    ):
        upgrade_rehearsal.reclaim_sql(seed)


@pytest.mark.parametrize(
    "written",
    [JOB_ID.upper(), "{" + JOB_ID + "}", "urn:uuid:" + JOB_ID],
)
def test_an_id_is_written_in_canonical_form(written: str) -> None:
    assert upgrade_rehearsal.reclaim_sql(ids(job=written)) == EXPECTED_SQL


@pytest.mark.parametrize(
    ("output", "expected"),
    [("1\n", True), ("2\n", True), ("0\n", False), (" 1 ", True)],
)
def test_a_count_is_read_as_a_record_or_none(
    output: str, expected: bool
) -> None:
    assert upgrade_rehearsal.parse_reclaim_count(output) is expected


@pytest.mark.parametrize("output", ["", "x", "1|2", "1\n2", "-1", "1.0"])
def test_an_answer_that_is_not_one_count_is_an_error(output: str) -> None:
    with pytest.raises(
        ValueError, match="unexpected reclaim count from the database"
    ):
        upgrade_rehearsal.parse_reclaim_count(output)


@pytest.mark.parametrize("output", ["\u0663", "\uff11"])
def test_a_digit_that_is_not_ascii_is_an_error(output: str) -> None:
    with pytest.raises(
        ValueError, match="unexpected reclaim count from the database"
    ):
        upgrade_rehearsal.parse_reclaim_count(output)


def test_the_query_runs_in_the_database_container() -> None:
    seen: list[list[str]] = []

    def compose(
        arguments: Sequence[str],
    ) -> subprocess.CompletedProcess[str]:
        seen.append(list(arguments))
        return completed("1\n")

    assert upgrade_rehearsal.reclaim_recorded(compose, ids()) is True
    assert seen == [
        [*upgrade_rehearsal._PSQL, "-At", "-c", EXPECTED_SQL]
    ]


def test_a_count_of_zero_is_no_record() -> None:
    def compose(
        arguments: Sequence[str],
    ) -> subprocess.CompletedProcess[str]:
        return completed("0\n")

    assert upgrade_rehearsal.reclaim_recorded(compose, ids()) is False


def test_a_failed_query_is_reported() -> None:
    def compose(
        arguments: Sequence[str],
    ) -> subprocess.CompletedProcess[str]:
        return completed("", 1, "boom")

    with pytest.raises(
        RuntimeError,
        match="the reclaim record query failed with exit code 1: boom",
    ):
        upgrade_rehearsal.reclaim_recorded(compose, ids())


def test_a_worker_with_no_job_passes_when_the_reclaim_is_recorded() -> None:
    read(served(idle_worker()), lambda: True, FakeTime())


def test_a_worker_holding_the_job_never_asks_for_the_record() -> None:
    command = list(upgrade_rehearsal.JOB_COMMAND)

    read(served(worker_holding(command)), never, FakeTime())


def test_the_record_is_waited_for() -> None:
    answers = iter([False, False, True])
    fake = FakeTime()

    read(served(idle_worker()), lambda: next(answers), fake)

    assert fake.sleeps == [upgrade_rehearsal.RECLAIM_INTERVAL] * 2


def test_the_wait_is_bounded_at_ten_seconds() -> None:
    assert upgrade_rehearsal.RECLAIM_TIMEOUT == 10.0


def test_without_a_record_the_run_fails_after_the_wait() -> None:
    fake = FakeTime()

    with pytest.raises(RuntimeError) as caught:
        read(served(idle_worker()), lambda: False, fake)

    assert str(caught.value) == PREFIX + NO_RECORD
    assert sum(fake.sleeps) == upgrade_rehearsal.RECLAIM_TIMEOUT


def test_a_different_command_never_asks_for_the_record() -> None:
    with pytest.raises(RuntimeError) as caught:
        read(served(worker_holding(["other"])), never, FakeTime())

    assert str(caught.value) == PREFIX + DIFFERENT_COMMAND


def test_a_failing_query_ends_the_wait_at_once() -> None:
    fake = FakeTime()

    def broken() -> bool:
        raise RuntimeError("the reclaim record query failed")

    with pytest.raises(RuntimeError, match="the reclaim record query failed"):
        read(served(idle_worker()), broken, fake)

    assert fake.sleeps == []


@pytest.mark.parametrize(
    "response",
    [(500, "{}"), (200, '{"id": "other"}'), (200, "nope")],
)
def test_a_wrong_worker_body_never_asks_for_the_record(
    response: tuple[int, str],
) -> None:
    with pytest.raises(RuntimeError) as caught:
        read(served(response), never, FakeTime())

    assert "reclaim record" not in str(caught.value)


def test_the_missing_record_is_reported_with_the_other_problems() -> None:
    responses = {
        NODE: (404, "{}"),
        WORKER: idle_worker(),
        JOB: ok("j-1"),
    }

    with pytest.raises(RuntimeError) as caught:
        read(responses, lambda: False, FakeTime())

    assert str(caught.value) == (
        PREFIX
        + f"GET {NODE} returned 404, expected 200; "
        + NO_RECORD
    )
