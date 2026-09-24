from __future__ import annotations

import random

import httpx
import pytest

from scripts.run_agent import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_CAP_SECONDS,
    INTERVAL_JITTER_FRACTION,
    AgentError,
    backoff_delay_seconds,
    call_with_retry,
    is_stale_view,
    is_transient,
    jittered_interval_seconds,
    register_with_retry,
    retry_after_seconds,
)


def _status_error(
    status_code: int,
    headers: dict[str, str] | None = None,
) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "http://testserver/x")
    response = httpx.Response(
        status_code,
        headers=headers,
        request=request,
    )

    return httpx.HTTPStatusError(
        "error",
        request=request,
        response=response,
    )


@pytest.mark.parametrize("status_code", [429, 500, 502, 503])
def test_server_side_statuses_are_transient(status_code: int) -> None:
    assert is_transient(_status_error(status_code)) is True


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 409, 422])
def test_client_side_statuses_are_not_transient(
    status_code: int,
) -> None:
    assert is_transient(_status_error(status_code)) is False


def test_transport_failures_are_transient() -> None:
    assert is_transient(httpx.ConnectError("refused")) is True
    assert is_transient(httpx.ReadTimeout("timed out")) is True


def test_only_404_and_409_mean_the_agents_view_is_stale() -> None:
    assert is_stale_view(_status_error(404)) is True
    assert is_stale_view(_status_error(409)) is True
    assert is_stale_view(_status_error(429)) is False
    assert is_stale_view(_status_error(401)) is False
    assert is_stale_view(httpx.ConnectError("refused")) is False


def test_retry_after_parses_integer_seconds() -> None:
    error = _status_error(429, {"Retry-After": "7"})

    assert retry_after_seconds(error) == 7.0


@pytest.mark.parametrize("raw", ["soon", "-3", ""])
def test_retry_after_ignores_malformed_values(raw: str) -> None:
    error = _status_error(429, {"Retry-After": raw})

    assert retry_after_seconds(error) is None


def test_retry_after_is_none_when_absent_or_not_a_status_error() -> None:
    assert retry_after_seconds(_status_error(503)) is None
    assert retry_after_seconds(httpx.ConnectError("refused")) is None


def test_backoff_delay_never_exceeds_the_cap() -> None:
    rng = random.Random(0)

    for attempt in range(60):
        assert 0.0 <= backoff_delay_seconds(attempt, None, rng) <= (
            BACKOFF_CAP_SECONDS
        )


def test_first_retry_is_bounded_by_the_base_delay() -> None:
    rng = random.Random(1)

    for _ in range(100):
        assert backoff_delay_seconds(0, None, rng) <= (
            BACKOFF_BASE_SECONDS
        )


def test_backoff_delay_honors_retry_after_as_a_floor() -> None:
    rng = random.Random(2)

    for attempt in range(10):
        assert backoff_delay_seconds(attempt, 12.0, rng) >= 12.0


def test_backoff_delay_is_deterministic_for_a_given_seed() -> None:
    first = backoff_delay_seconds(4, None, random.Random(42))
    second = backoff_delay_seconds(4, None, random.Random(42))

    assert first == second


def test_interval_jitter_stays_within_configured_fraction() -> None:
    rng = random.Random(3)
    base = 5.0
    spread = base * INTERVAL_JITTER_FRACTION

    for _ in range(200):
        value = jittered_interval_seconds(base, rng)
        assert base - spread <= value <= base + spread


def test_call_with_retry_retries_transient_failures_then_succeeds() -> None:
    sleeps: list[float] = []
    calls = {"count": 0}

    def operation() -> str:
        calls["count"] += 1

        if calls["count"] <= 2:
            raise _status_error(429)

        return "ok"

    result = call_with_retry(
        operation,
        description="test",
        sleep=sleeps.append,
        rng=random.Random(0),
    )

    assert result == "ok"
    assert calls["count"] == 3
    assert len(sleeps) == 2


def test_call_with_retry_does_not_retry_non_transient_failures() -> None:
    sleeps: list[float] = []
    calls = {"count": 0}

    def operation() -> str:
        calls["count"] += 1
        raise _status_error(401)

    with pytest.raises(httpx.HTTPStatusError):
        call_with_retry(
            operation,
            description="test",
            sleep=sleeps.append,
            rng=random.Random(0),
        )

    assert calls["count"] == 1
    assert sleeps == []


def test_call_with_retry_waits_at_least_retry_after() -> None:
    sleeps: list[float] = []
    calls = {"count": 0}

    def operation() -> str:
        calls["count"] += 1

        if calls["count"] == 1:
            raise _status_error(429, {"Retry-After": "3"})

        return "ok"

    call_with_retry(
        operation,
        description="test",
        sleep=sleeps.append,
        rng=random.Random(0),
    )

    assert sleeps[0] >= 3.0


def test_register_with_retry_survives_rate_limiting() -> None:
    sleeps: list[float] = []
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1

        if calls["count"] == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "2"},
                json={"detail": "rate limit exceeded"},
            )

        return httpx.Response(
            201,
            json={"id": "worker-1", "status": "IDLE"},
        )

    client = httpx.Client(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )

    worker_id = register_with_retry(
        client,
        "node-1",
        sleep=sleeps.append,
        rng=random.Random(0),
    )

    assert worker_id == "worker-1"
    assert calls["count"] == 2
    assert sleeps[0] >= 2.0


def test_register_with_retry_fails_fast_when_node_is_unknown() -> None:
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"detail": "Node not found."},
        )

    client = httpx.Client(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(AgentError, match="Node not found"):
        register_with_retry(
            client,
            "node-1",
            sleep=sleeps.append,
            rng=random.Random(0),
        )

    assert sleeps == []
