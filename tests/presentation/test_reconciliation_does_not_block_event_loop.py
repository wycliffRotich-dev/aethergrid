"""
Regression test: a reconciliation pass stuck on an unreachable
database must not stall the event loop.

With the database down, every repository call waits for the
connection pool's timeout (30 seconds by default). Called
directly from the event loop, that wait freezes every request
the server handles. The blocking call is simulated with
time.sleep so the test needs no database and runs in well under
a second.
"""

import asyncio
import time

from app.presentation.api import _run_cluster_tick

BLOCKING_CALL_SECONDS = 0.5
LAG_SAMPLE_INTERVAL_SECONDS = 0.01
MAX_ACCEPTABLE_LOOP_LAG_SECONDS = 0.2


class _ImmediateClusterTickService:
    def execute(self) -> None:
        return None


class _BlockingReconciliationLoop:
    """
    Stands in for a reconciliation pass waiting on a connection
    pool whose database is unreachable.
    """

    def execute(self) -> None:
        time.sleep(BLOCKING_CALL_SECONDS)


async def _measure_max_loop_lag(stop: asyncio.Event) -> float:
    """
    Repeatedly sleep for a short, known interval and record how
    much later than requested the event loop resumed this
    coroutine. A blocked loop shows up as lag.
    """
    max_lag = 0.0

    while not stop.is_set():
        started = time.perf_counter()
        await asyncio.sleep(LAG_SAMPLE_INTERVAL_SECONDS)
        elapsed = time.perf_counter() - started
        max_lag = max(max_lag, elapsed - LAG_SAMPLE_INTERVAL_SECONDS)

    return max_lag


async def _run_tick_while_measuring_lag() -> float:
    stop = asyncio.Event()
    monitor = asyncio.create_task(_measure_max_loop_lag(stop))
    await asyncio.sleep(0)

    await _run_cluster_tick(
        _ImmediateClusterTickService(),
        _BlockingReconciliationLoop(),
    )

    stop.set()
    return await monitor


def test_blocking_reconciliation_does_not_stall_the_event_loop() -> None:
    max_lag = asyncio.run(_run_tick_while_measuring_lag())

    assert max_lag < MAX_ACCEPTABLE_LOOP_LAG_SECONDS, (
        f"event loop was blocked for {max_lag:.3f}s while "
        f"reconciliation ran"
    )
