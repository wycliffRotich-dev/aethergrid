from __future__ import annotations

import pytest

from app.presentation.api import _run_cluster_tick


class FakeClusterTickService:
    """
    Fake cluster tick service whose execute() can be made to
    raise, to prove _run_cluster_tick isolates it from
    reconciliation.
    """

    def __init__(self, raises: bool = False) -> None:
        self.raises = raises
        self.executed = False

    def execute(self) -> None:
        self.executed = True
        if self.raises:
            raise RuntimeError("simulated cluster tick failure")


class FakeReconciliationLoop:
    """
    Fake reconciliation loop whose execute() can be made to
    raise, to prove _run_cluster_tick isolates it from the
    cluster tick and from the next call to itself.
    """

    def __init__(self, raises: bool = False) -> None:
        self.raises = raises
        self.executed = False

    def execute(self) -> None:
        self.executed = True
        if self.raises:
            raise RuntimeError("simulated reconciliation failure")


@pytest.mark.asyncio
async def test_reconciliation_runs_even_if_cluster_tick_raises() -> None:
    cluster_tick_service = FakeClusterTickService(raises=True)
    reconciliation_loop = FakeReconciliationLoop(raises=False)

    await _run_cluster_tick(cluster_tick_service, reconciliation_loop)

    assert cluster_tick_service.executed is True
    assert reconciliation_loop.executed is True


@pytest.mark.asyncio
async def test_tick_does_not_raise_when_reconciliation_fails() -> None:
    cluster_tick_service = FakeClusterTickService(raises=False)
    reconciliation_loop = FakeReconciliationLoop(raises=True)

    # Must not propagate: a failure here must not be able to
    # kill the outer while-loop in _run_cluster_loop, or every
    # future tick (cluster tick included) stops forever.
    await _run_cluster_tick(cluster_tick_service, reconciliation_loop)

    assert cluster_tick_service.executed is True
    assert reconciliation_loop.executed is True


@pytest.mark.asyncio
async def test_tick_does_not_raise_when_cluster_tick_fails() -> None:
    cluster_tick_service = FakeClusterTickService(raises=True)
    reconciliation_loop = FakeReconciliationLoop(raises=False)

    # Must not propagate for the same reason as above, mirrored
    # for the cluster tick phase.
    await _run_cluster_tick(cluster_tick_service, reconciliation_loop)


@pytest.mark.asyncio
async def test_both_phases_attempted_even_when_both_fail() -> None:
    cluster_tick_service = FakeClusterTickService(raises=True)
    reconciliation_loop = FakeReconciliationLoop(raises=True)

    # Neither phase should be able to suppress the other from
    # being attempted, and the function itself must still
    # return normally so the driving while-loop keeps ticking.
    await _run_cluster_tick(cluster_tick_service, reconciliation_loop)

    assert cluster_tick_service.executed is True
    assert reconciliation_loop.executed is True
