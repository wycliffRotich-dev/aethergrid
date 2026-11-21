"""
ADR 0102, decision 5. Slow reads must not starve the health route.

The routes are plain functions, so each read holds one worker thread of the
server while it waits. The limiter bounds the rate of requests and not the
number in flight. These tests run every request in one event loop, because
the thread limiter belongs to the loop. A test client that opens a loop for
each request would hide the problem.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any

import anyio
import httpx
import pytest

from app.presentation.public import app as public_app_module
from app.presentation.public.app import create_public_app
from tests.support.public_app import FakePublicReader, make_settings

STUCK_READS = 40
THREAD_SLOTS_USED_AT_LEAST = 20


class BlockingReader(FakePublicReader):
    """list_nodes waits until the test lets it go and counts each entry."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()
        self.entered = 0
        self._lock = threading.Lock()

    def list_nodes(self, limit: int) -> Any:
        with self._lock:
            self.entered += 1

        self.release.wait(timeout=30)

        return []


async def _get(app: Any, path: str, number: int) -> httpx.Response:
    address = (f"10.0.{number // 250}.{number % 250 + 1}", 5000)
    transport = httpx.ASGITransport(app=app, client=address)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def _until(condition: Callable[[], bool], seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds

    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("the reads never started")

        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_health_answers_while_many_reads_are_stuck() -> None:
    reader = BlockingReader()
    app = create_public_app(make_settings(), reader=reader)
    tasks: list[asyncio.Task[httpx.Response]] = []

    try:
        tasks = [
            asyncio.create_task(_get(app, "/public/nodes", number))
            for number in range(STUCK_READS)
        ]
        await _until(lambda: reader.entered >= THREAD_SLOTS_USED_AT_LEAST)
        await asyncio.sleep(0.3)

        health = await asyncio.wait_for(_get(app, "/healthz", 99), timeout=1.5)

        assert health.status_code == 200

        reader.release.set()
        answers = await asyncio.gather(*tasks)

        assert 429 not in {answer.status_code for answer in answers}
    finally:
        reader.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_health_answers_with_no_reads_stuck() -> None:
    app = create_public_app(make_settings(), reader=BlockingReader())

    health = await asyncio.wait_for(_get(app, "/healthz", 1), timeout=1.5)

    assert health.status_code == 200


@pytest.mark.asyncio
async def test_a_read_past_the_cap_is_refused_at_once_and_the_cap_frees() -> None:
    cap = public_app_module.MAX_READS_IN_FLIGHT
    reader = BlockingReader()
    app = create_public_app(make_settings(), reader=reader)
    tasks: list[asyncio.Task[httpx.Response]] = []

    try:
        tasks = [
            asyncio.create_task(_get(app, "/public/nodes", number))
            for number in range(cap)
        ]
        await _until(lambda: reader.entered >= cap)

        refused = await asyncio.wait_for(
            _get(app, "/public/nodes", cap + 1), timeout=1.5
        )

        assert refused.status_code == 503
        assert refused.content == b'{"error":"unavailable"}'
        assert reader.entered == cap

        reader.release.set()
        answers = await asyncio.gather(*tasks)

        assert {answer.status_code for answer in answers} == {200}

        again = await asyncio.wait_for(
            _get(app, "/public/nodes", cap + 2), timeout=1.5
        )

        assert again.status_code == 200
    finally:
        reader.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_the_cap_leaves_server_threads_free() -> None:
    slots = anyio.to_thread.current_default_thread_limiter().total_tokens

    assert public_app_module.MAX_READS_IN_FLIGHT <= slots - 10


@pytest.mark.asyncio
async def test_health_answers_with_every_thread_held_even_without_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(public_app_module, "MAX_READS_IN_FLIGHT", 1000)
    reader = BlockingReader()
    app = create_public_app(make_settings(), reader=reader)
    tasks: list[asyncio.Task[httpx.Response]] = []

    try:
        tasks = [
            asyncio.create_task(_get(app, "/public/nodes", number))
            for number in range(45)
        ]
        await _until(lambda: reader.entered >= 40)

        health = await asyncio.wait_for(_get(app, "/healthz", 99), timeout=1.5)

        assert health.status_code == 200
    finally:
        reader.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_each_app_has_its_own_cap() -> None:
    cap = public_app_module.MAX_READS_IN_FLIGHT
    blocked = BlockingReader()
    busy = create_public_app(make_settings(), reader=blocked)
    other = create_public_app(make_settings(), reader=FakePublicReader())
    tasks: list[asyncio.Task[httpx.Response]] = []

    try:
        tasks = [
            asyncio.create_task(_get(busy, "/public/nodes", number))
            for number in range(cap)
        ]
        await _until(lambda: blocked.entered >= cap)

        served = await asyncio.wait_for(
            _get(other, "/public/nodes", cap + 1), timeout=1.5
        )

        assert served.status_code == 200
    finally:
        blocked.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
