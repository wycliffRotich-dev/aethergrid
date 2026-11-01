from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence

import pytest

from scripts import upgrade_rehearsal

PSQL = ["exec", "-T", "postgres", "psql", "-U", "neuromesh", "-d", "neuromesh"]


class FakeCompose:
    """Answers compose commands from a script and keeps what it was asked."""

    def __init__(self, answers: dict[str, list[tuple[int, str, str]]]) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(
        self,
        arguments: Sequence[str],
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(arguments))
        key = " ".join(arguments)
        for pattern, replies in self.answers.items():
            if pattern in key:
                code, out, err = replies.pop(0) if len(replies) > 1 else replies[0]
                return subprocess.CompletedProcess(list(arguments), code, out, err)
        raise AssertionError(f"unexpected compose call: {key}")


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def run_at_rest(compose: FakeCompose, fake: FakeTime) -> None:
    upgrade_rehearsal.at_rest(compose, clock=fake.clock, sleep=fake.sleep)


def test_at_rest_returns_once_a_lease_and_a_busy_worker_exist() -> None:
    compose = FakeCompose(
        {"exec": [(0, "0|0\n", ""), (0, "1|0\n", ""), (0, "1|1\n", "")]}
    )
    fake = FakeTime()

    run_at_rest(compose, fake)

    assert len(compose.calls) == 3
    assert fake.sleeps == [0.25, 0.25]


def test_at_rest_asks_the_database_with_the_assignment_query() -> None:
    compose = FakeCompose({"exec": [(0, "1|1\n", "")]})

    run_at_rest(compose, FakeTime())

    assert compose.calls == [[*PSQL, "-At", "-c", upgrade_rehearsal.ASSIGNMENT_SQL]]


def test_at_rest_gives_up_before_the_lease_can_expire() -> None:
    compose = FakeCompose({"exec": [(0, "0|0\n", "")]})
    fake = FakeTime()

    with pytest.raises(TimeoutError, match="waiting for the seeded cluster"):
        run_at_rest(compose, fake)

    assert sum(fake.sleeps) == 25.0
    assert sum(fake.sleeps) < 30.0


def test_a_failing_psql_ends_the_wait_with_its_error() -> None:
    compose = FakeCompose({"exec": [(2, "", "psql: connection refused\n")]})
    fake = FakeTime()

    with pytest.raises(RuntimeError, match="exit code 2: psql: connection refused"):
        run_at_rest(compose, fake)

    assert fake.sleeps == []


def inspect_of(state: str) -> Callable[[str], str]:
    def inspect(container_id: str) -> str:
        assert container_id == "abc123"
        return state

    return inspect


def test_the_api_is_stopped_and_its_exit_state_checked() -> None:
    compose = FakeCompose(
        {"stop neuromesh": [(0, "", "")], "ps -aq neuromesh": [(0, "abc123\n", "")]}
    )

    upgrade_rehearsal.stop_old_api(compose, inspect_of("exited 0\n"))

    assert compose.calls == [["stop", "neuromesh"], ["ps", "-aq", "neuromesh"]]


def test_a_killed_api_is_an_error_from_the_stop() -> None:
    compose = FakeCompose(
        {"stop neuromesh": [(0, "", "")], "ps -aq neuromesh": [(0, "abc123\n", "")]}
    )

    with pytest.raises(RuntimeError, match="killed"):
        upgrade_rehearsal.stop_old_api(compose, inspect_of("exited 137\n"))


def test_a_failed_stop_is_reported_with_its_error() -> None:
    compose = FakeCompose({"stop neuromesh": [(1, "", "no such service\n")]})

    with pytest.raises(RuntimeError, match="stopping the API failed.*no such service"):
        upgrade_rehearsal.stop_old_api(compose, inspect_of("exited 0\n"))


@pytest.mark.parametrize("output", ["", "\n", "abc\ndef\n"])
def test_a_missing_or_ambiguous_container_is_an_error(output: str) -> None:
    compose = FakeCompose(
        {"stop neuromesh": [(0, "", "")], "ps -aq neuromesh": [(0, output, "")]}
    )

    with pytest.raises(RuntimeError, match="exactly one API container"):
        upgrade_rehearsal.stop_old_api(compose, inspect_of("exited 0\n"))


def test_the_snapshot_exports_each_listed_table() -> None:
    compose = FakeCompose(
        {
            "SELECT format": [(0, "public.items\nctx_a.\"Odd Table\"\n", "")],
            "COPY public.items": [(0, "id\n1\n", "")],
            'COPY ctx_a."Odd Table"': [(0, "id\n2\n", "")],
        }
    )

    assert upgrade_rehearsal.snapshot(compose) == {
        "public.items": "id\n1\n",
        'ctx_a."Odd Table"': "id\n2\n",
    }


def test_a_failed_export_names_the_table_and_the_error() -> None:
    compose = FakeCompose(
        {
            "SELECT format": [(0, "public.items\n", "")],
            "COPY public.items": [(1, "", "permission denied\n")],
        }
    )

    with pytest.raises(RuntimeError, match="exporting public.items failed.*permission denied"):
        upgrade_rehearsal.snapshot(compose)
