"""
End-to-end tests: the real ResilientAPIClient against a real HTTP server.

test_resilient_api_client.py mocks the HTTP layer with respx, which is
fast and precise but never touches a socket. These tests do, so they
cover what a transport mock cannot: real read timeouts, real refused
connections, and real header handling on the wire.

Run with: pytest integrations/resilient_client/test_resilient_client_e2e.py -v
"""

import socket
import threading
import time
import uuid
from dataclasses import dataclass

import httpx
import pytest
import uvicorn
from mock_partner_server import (
    VALID_CLIENT_ID,
    VALID_CLIENT_SECRET,
    MockState,
    create_app,
)
from resilient_api_client import (
    AuthError,
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    ClientError,
    OAuth2Config,
    RateLimitError,
    ResilientAPIClient,
    ResilientClientConfig,
    RetryConfig,
    RetryExhaustedError,
    ServerError,
)

FAST_RETRY = RetryConfig(max_attempts=4, base_delay_s=0.01, max_delay_s=0.05, jitter_s=0.0)
SINGLE_ATTEMPT = RetryConfig(max_attempts=1, base_delay_s=0.01, max_delay_s=0.05, jitter_s=0.0)


@dataclass
class RunningServer:
    base_url: str
    state: MockState


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    app, state = create_app()
    port = _free_port()
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"
    )
    uvicorn_server = uvicorn.Server(config)
    thread = threading.Thread(target=uvicorn_server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 5
    while not uvicorn_server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("mock server did not start within 5 seconds")
        time.sleep(0.01)

    yield RunningServer(base_url=f"http://127.0.0.1:{port}", state=state)

    uvicorn_server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(autouse=True)
def isolate(server, monkeypatch):
    """Fresh counters per test, and never route localhost through a proxy."""
    server.state.reset()
    server.state.token_ttl_s = 300
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


def make_client(base_url: str, **overrides) -> ResilientAPIClient:
    config = ResilientClientConfig(
        base_url=base_url,
        timeout_s=overrides.pop("timeout_s", 2.0),
        retry=overrides.pop("retry", FAST_RETRY),
        circuit_breaker=overrides.pop(
            "circuit_breaker", CircuitBreaker(failure_threshold=5, reset_timeout_s=30)
        ),
        **overrides,
    )
    return ResilientAPIClient(config)


def unique_key() -> str:
    return uuid.uuid4().hex


# -- happy path and transient failures ---------------------------------------


def test_success_over_real_http(server):
    with make_client(server.base_url) as client:
        assert client.get("/v1/ok") == {"ok": True}
    assert server.state.hits["/v1/ok"] == 1


def test_recovers_from_transient_503s(server):
    key = unique_key()
    with make_client(server.base_url) as client:
        result = client.get(f"/v1/flaky?key={key}&fail_first=2")

    assert result["ok"] is True
    assert result["call_number"] == 3
    assert server.state.hits["/v1/flaky"] == 3


def test_persistent_503_raises_server_error_after_all_attempts(server):
    with make_client(server.base_url) as client, pytest.raises(ServerError) as exc_info:
        client.get("/v1/always-down")

    assert exc_info.value.status_code == 503
    assert server.state.hits["/v1/always-down"] == FAST_RETRY.max_attempts


# -- rate limiting -------------------------------------------------------------


def test_honors_retry_after_header_from_a_real_response(server):
    key = unique_key()
    retry = RetryConfig(max_attempts=2, base_delay_s=0.01, max_delay_s=0.05, jitter_s=0.0)

    with make_client(server.base_url, retry=retry) as client:
        started = time.monotonic()
        result = client.get(f"/v1/ratelimited?key={key}&fail_first=1&retry_after=1")
        elapsed = time.monotonic() - started

    assert result["ok"] is True
    # The configured backoff is ~0.01s. Waiting about a second proves the
    # client obeyed the server's header rather than its own backoff.
    assert 0.9 <= elapsed < 3.0


def test_persistent_429_raises_rate_limit_error_with_retry_after(server):
    key = unique_key()
    retry = RetryConfig(max_attempts=2, base_delay_s=0.01, max_delay_s=0.05, jitter_s=0.0,
                        max_retry_after_s=0.05)

    with make_client(server.base_url, retry=retry) as client:
        with pytest.raises(RateLimitError) as exc_info:
            client.get(f"/v1/ratelimited?key={key}&fail_first=99&retry_after=120")

    # 120s from the server, clamped to our configured ceiling.
    assert exc_info.value.retry_after_s == 0.05


# -- failures that only exist on a real network -------------------------------


def test_read_timeout_surfaces_as_retry_exhausted(server):
    retry = RetryConfig(max_attempts=2, base_delay_s=0.01, max_delay_s=0.05, jitter_s=0.0)

    with make_client(server.base_url, timeout_s=0.1, retry=retry) as client:
        with pytest.raises(RetryExhaustedError) as exc_info:
            client.get("/v1/slow?delay=0.5")

    assert isinstance(exc_info.value.last_exception, httpx.TimeoutException)
    assert server.state.hits["/v1/slow"] == 2


def test_connection_refused_surfaces_as_retry_exhausted():
    dead_url = f"http://127.0.0.1:{_free_port()}"  # nothing is listening here
    breaker = CircuitBreaker(failure_threshold=5, reset_timeout_s=30)

    with make_client(dead_url, circuit_breaker=breaker) as client:
        with pytest.raises(RetryExhaustedError) as exc_info:
            client.get("/v1/ok")

    assert isinstance(exc_info.value.last_exception, httpx.ConnectError)
    assert breaker._consecutive_failures == 1


# -- client errors and the circuit breaker ------------------------------------


def test_404_is_a_single_attempt_and_never_trips_the_breaker(server):
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_s=30)

    with make_client(server.base_url, circuit_breaker=breaker) as client:
        for _ in range(5):
            with pytest.raises(ClientError) as exc_info:
                client.get("/v1/missing")
            assert exc_info.value.status_code == 404

    assert server.state.hits["/v1/missing"] == 5, "each 404 must be exactly one attempt"
    assert breaker.state == CircuitState.CLOSED


def test_open_breaker_fails_fast_without_touching_the_network(server):
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_s=30)

    with make_client(server.base_url, retry=SINGLE_ATTEMPT, circuit_breaker=breaker) as client:
        for _ in range(2):
            with pytest.raises(ServerError):
                client.get("/v1/always-down")
        assert breaker.state == CircuitState.OPEN

        with pytest.raises(CircuitOpenError):
            client.get("/v1/always-down")

    # Two real requests reached the server. The third never left the client.
    assert server.state.hits["/v1/always-down"] == 2


def test_breaker_recovers_once_the_server_heals(server):
    key = unique_key()
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_s=0.2)

    with make_client(server.base_url, retry=SINGLE_ATTEMPT, circuit_breaker=breaker) as client:
        path = f"/v1/flaky?key={key}&fail_first=2"
        for _ in range(2):
            with pytest.raises(ServerError):
                client.get(path)
        assert breaker.state == CircuitState.OPEN

        time.sleep(0.25)
        assert breaker.state == CircuitState.HALF_OPEN

        assert client.get(path)["ok"] is True
        assert breaker.state == CircuitState.CLOSED


# -- OAuth2 over the wire ------------------------------------------------------


def _oauth(server, **overrides) -> OAuth2Config:
    return OAuth2Config(
        token_url=f"{server.base_url}/oauth/token",
        client_id=overrides.pop("client_id", VALID_CLIENT_ID),
        client_secret=overrides.pop("client_secret", VALID_CLIENT_SECRET),
        **overrides,
    )


def test_oauth_token_is_fetched_once_and_reused(server):
    with make_client(server.base_url, oauth2=_oauth(server)) as client:
        assert client.get("/v1/secure") == {"secure": True}
        assert client.get("/v1/secure") == {"secure": True}

    assert server.state.tokens_issued == 1
    assert server.state.hits["/v1/secure"] == 2


def test_oauth_token_is_refreshed_after_it_expires(server):
    server.state.token_ttl_s = 1

    with make_client(server.base_url, oauth2=_oauth(server, expiry_skew_s=0.0)) as client:
        client.get("/v1/secure")
        time.sleep(1.1)
        client.get("/v1/secure")

    assert server.state.tokens_issued == 2


def test_wrong_client_secret_raises_auth_error(server):
    config = _oauth(server, client_secret="wrong")

    with make_client(server.base_url, oauth2=config) as client:
        with pytest.raises(AuthError):
            client.get("/v1/secure")

    assert server.state.hits["/v1/secure"] == 0, "must not call the API without a token"


# -- retry safety for non idempotent requests --------------------------------
#
# The server applies a payment BEFORE the response goes wrong, so any replay of
# the same POST is a duplicate charge. These tests prove the client no longer
# replays it unless doing so is provably safe.


def test_post_is_not_replayed_after_a_5xx_and_says_the_outcome_is_unknown(server):
    key = unique_key()

    with make_client(server.base_url) as client, pytest.raises(ServerError) as exc_info:
        client.post(f"/v1/payments?key={key}&fail_first=1", json={"amount": 100})

    assert exc_info.value.status_code == 503
    assert exc_info.value.outcome_unknown is True
    assert server.state.hits["/v1/payments"] == 1, "a POST must not be replayed"
    assert server.state.payments_applied == 1, "exactly one charge, never two"


def test_post_read_timeout_is_not_replayed(server):
    key = unique_key()

    with make_client(server.base_url, timeout_s=0.1) as client:
        with pytest.raises(RetryExhaustedError) as exc_info:
            client.post(f"/v1/payments?key={key}&delay=0.5", json={"amount": 100})

    assert isinstance(exc_info.value.last_exception, httpx.TimeoutException)
    assert exc_info.value.outcome_unknown is True
    # The server did act on the request that timed out, and only that once.
    assert server.state.payments_applied == 1


def test_post_with_idempotency_key_is_retried_and_applied_exactly_once(server):
    key = unique_key()

    with make_client(server.base_url) as client:
        result = client.post(
            f"/v1/payments?key={key}&fail_first=1",
            json={"amount": 100},
            idempotency_key=f"order-{key}",
        )

    # First attempt: applied, then the response was lost (503). The retry
    # carried the same key, so the server replayed the result instead of
    # charging again.
    assert result == {"payment_id": 1, "replayed": True}
    assert server.state.hits["/v1/payments"] == 2
    assert server.state.payments_applied == 1


def test_post_that_never_reached_the_server_is_still_retried():
    dead_url = f"http://127.0.0.1:{_free_port()}"  # nothing is listening here
    breaker = CircuitBreaker(failure_threshold=99, reset_timeout_s=30)

    with make_client(dead_url, circuit_breaker=breaker) as client:
        started = time.monotonic()
        with pytest.raises(RetryExhaustedError) as exc_info:
            client.post("/v1/payments", json={"amount": 100})
        elapsed = time.monotonic() - started

    assert isinstance(exc_info.value.last_exception, httpx.ConnectError)
    assert exc_info.value.outcome_unknown is False, "a refused connection provably sent nothing"
    # FAST_RETRY makes 4 attempts with 0.01s, 0.02s, 0.04s backoff. A single
    # attempt would return almost instantly, so this proves it did retry.
    assert elapsed >= 0.06
