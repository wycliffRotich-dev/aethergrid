from __future__ import annotations

from collections.abc import Callable

import pytest

from scripts import upgrade_rehearsal


class FakeTime:
    """A clock that moves only when something sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Scripted:
    """A check that gives its answers in order, then repeats the last."""

    def __init__(self, answers: list[bool]) -> None:
        self.answers = answers
        self.calls = 0

    def __call__(self) -> bool:
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return answer


def run(
    check: Callable[[], bool],
    fake: FakeTime,
    *,
    timeout: float,
    interval: float = 0.25,
) -> None:
    upgrade_rehearsal.wait_until(
        check,
        timeout=timeout,
        interval=interval,
        describe="the lease",
        clock=fake.clock,
        sleep=fake.sleep,
    )


def test_a_check_that_is_already_true_returns_without_sleeping() -> None:
    fake = FakeTime()
    check = Scripted([True])

    run(check, fake, timeout=10.0)

    assert check.calls == 1
    assert fake.sleeps == []


def test_the_check_is_repeated_at_the_interval_until_it_is_true() -> None:
    fake = FakeTime()
    check = Scripted([False, False, True])

    run(check, fake, timeout=10.0)

    assert check.calls == 3
    assert fake.sleeps == [0.25, 0.25]


def test_a_check_that_never_passes_times_out_naming_the_wait() -> None:
    fake = FakeTime()
    check = Scripted([False])

    with pytest.raises(
        TimeoutError, match="timed out after 1.0s waiting for the lease"
    ):
        run(check, fake, timeout=1.0)

    assert sum(fake.sleeps) == 1.0


def test_the_check_runs_once_more_when_the_deadline_is_reached() -> None:
    fake = FakeTime()
    check = Scripted([False])

    with pytest.raises(TimeoutError):
        run(check, fake, timeout=1.0)

    assert check.calls == 5


def test_the_last_sleep_is_cut_to_what_is_left_of_the_timeout() -> None:
    fake = FakeTime()
    check = Scripted([False])

    with pytest.raises(TimeoutError):
        run(check, fake, timeout=1.0, interval=0.375)

    assert fake.sleeps == [0.375, 0.375, 0.25]


def test_an_error_in_the_check_is_not_retried() -> None:
    fake = FakeTime()

    def broken() -> bool:
        raise RuntimeError("docker is gone")

    with pytest.raises(RuntimeError, match="docker is gone"):
        run(broken, fake, timeout=10.0)

    assert fake.sleeps == []
