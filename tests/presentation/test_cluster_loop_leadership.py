import asyncio
import contextlib
import time

import pytest

from app.application.scheduler_leadership import SchedulerLeadership
from app.presentation import api


class FakeLeadership(SchedulerLeadership):
    def __init__(
        self,
        leads: bool = True,
        error: Exception | None = None,
    ) -> None:
        self.leads = leads
        self.error = error
        self.released = 0

    def try_acquire(self) -> bool:
        if self.error is not None:
            raise self.error
        return self.leads

    def release(self) -> None:
        self.released += 1


class CountingService:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self) -> None:
        self.calls += 1


def test_a_follower_skips_the_tick() -> None:
    tick = CountingService()
    reconciliation = CountingService()

    asyncio.run(
        api._run_leader_tick(
            FakeLeadership(leads=False),
            tick,
            reconciliation,
        )
    )

    assert tick.calls == 0
    assert reconciliation.calls == 0


def test_a_leader_runs_the_tick_and_the_reconciliation() -> None:
    tick = CountingService()
    reconciliation = CountingService()

    asyncio.run(
        api._run_leader_tick(
            FakeLeadership(leads=True),
            tick,
            reconciliation,
        )
    )

    assert tick.calls == 1
    assert reconciliation.calls == 1


def test_a_failing_election_skips_the_tick_and_does_not_raise() -> None:
    tick = CountingService()
    reconciliation = CountingService()

    asyncio.run(
        api._run_leader_tick(
            FakeLeadership(error=RuntimeError("database gone")),
            tick,
            reconciliation,
        )
    )

    assert tick.calls == 0
    assert reconciliation.calls == 0


def test_the_loop_releases_leadership_when_it_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leadership = FakeLeadership(leads=True)
    tick = CountingService()
    reconciliation = CountingService()
    monkeypatch.setattr(api, "get_scheduler_leadership", lambda: leadership)
    monkeypatch.setattr(api, "get_cluster_tick_service", lambda: tick)
    monkeypatch.setattr(api, "get_reconciliation_loop", lambda: reconciliation)

    async def scenario() -> None:
        task = asyncio.create_task(api._run_cluster_loop())
        deadline = time.monotonic() + 5.0
        while tick.calls == 0:
            assert time.monotonic() < deadline, "the loop never ticked"
            await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert tick.calls >= 1
    assert leadership.released == 1
