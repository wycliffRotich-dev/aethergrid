"""
Tests for ResilientAPIClient. Run with: pytest test_resilient_api_client.py -v

Uses respx to mock the HTTP layer, so no real network/gov endpoint needed.
"""

import httpx
import pytest
import respx
from resilient_api_client import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    ClientError,
    ConfigError,
    MTLSConfig,
    OAuth2Config,
    RateLimitError,
    ResilientAPIClient,
    ResilientClientConfig,
    RetryConfig,
    RetryExhaustedError,
    ServerError,
)

BASE_URL = "https://api.example-partner.com"


def make_client(**overrides) -> ResilientAPIClient:
    config = ResilientClientConfig(
        base_url=BASE_URL,
        timeout_s=2.0,
        retry=overrides.pop("retry", RetryConfig(max_attempts=3, base_delay_s=0.01,
                                                  max_delay_s=0.02, jitter_s=0.0)),
        circuit_breaker=overrides.pop("circuit_breaker", CircuitBreaker(
            failure_threshold=2, reset_timeout_s=0.1
        )),
        **overrides,
    )
    return ResilientAPIClient(config)


# -- basic success / retry / exhaustion --------------------------------

@respx.mock
def test_successful_get_returns_json():
    respx.get(f"{BASE_URL}/v1/status").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    client = make_client()
    assert client.get("/v1/status") == {"status": "ok"}


@respx.mock
def test_retries_on_transient_5xx_then_succeeds():
    route = respx.get(f"{BASE_URL}/v1/flaky")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(503),
        httpx.Response(200, json={"ok": True}),
    ]
    client = make_client(retry=RetryConfig(max_attempts=3, base_delay_s=0.01,
                                            max_delay_s=0.02, jitter_s=0.0))
    result = client.get("/v1/flaky")
    assert result == {"ok": True}
    assert route.call_count == 3


@respx.mock
def test_exhausts_retries_and_raises_server_error():
    respx.get(f"{BASE_URL}/v1/always-down").mock(
        return_value=httpx.Response(503)
    )
    client = make_client(retry=RetryConfig(max_attempts=2, base_delay_s=0.01,
                                            max_delay_s=0.02, jitter_s=0.0))
    with pytest.raises(ServerError) as exc_info:
        client.get("/v1/always-down")
    assert exc_info.value.status_code == 503


@respx.mock
def test_transport_error_exhaustion_raises_retry_exhausted():
    respx.get(f"{BASE_URL}/v1/unreachable").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    client = make_client(retry=RetryConfig(max_attempts=2, base_delay_s=0.01,
                                            max_delay_s=0.02, jitter_s=0.0))
    with pytest.raises(RetryExhaustedError):
        client.get("/v1/unreachable")


# -- structured client errors, no retry, no breaker impact --------------

@respx.mock
def test_non_retryable_4xx_fails_fast_as_client_error():
    route = respx.get(f"{BASE_URL}/v1/not-found").mock(
        return_value=httpx.Response(404, text="not found")
    )
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_s=10)
    client = make_client(
        retry=RetryConfig(max_attempts=5, base_delay_s=0.01, max_delay_s=0.02, jitter_s=0.0),
        circuit_breaker=breaker,
    )
    with pytest.raises(ClientError) as exc_info:
        client.get("/v1/not-found")

    assert exc_info.value.status_code == 404
    assert route.call_count == 1, "a client error should never be retried"
    assert breaker.state == CircuitState.CLOSED, (
        "a 404 is a client mistake, not endpoint degradation, and must not "
        "count toward tripping the circuit breaker"
    )


@respx.mock
def test_repeated_404s_never_trip_the_breaker():
    respx.get(f"{BASE_URL}/v1/missing").mock(return_value=httpx.Response(404))
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_s=10)
    client = make_client(circuit_breaker=breaker)

    for _ in range(5):
        with pytest.raises(ClientError):
            client.get("/v1/missing")

    assert breaker.state == CircuitState.CLOSED


# -- rate limiting and Retry-After ---------------------------------------

@respx.mock
def test_honors_retry_after_seconds_header():
    route = respx.get(f"{BASE_URL}/v1/limited")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0.02"}),
        httpx.Response(200, json={"ok": True}),
    ]
    client = make_client(retry=RetryConfig(max_attempts=2, base_delay_s=5.0,
                                            max_delay_s=5.0, jitter_s=0.0))
    start = __import__("time").monotonic()
    result = client.get("/v1/limited")
    elapsed = __import__("time").monotonic() - start

    assert result == {"ok": True}
    # Should have waited ~0.02s (the header), not ~5s (the configured backoff)
    assert elapsed < 1.0


@respx.mock
def test_rate_limit_exhaustion_raises_rate_limit_error_with_retry_after():
    respx.get(f"{BASE_URL}/v1/limited").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "3"})
    )
    client = make_client(retry=RetryConfig(max_attempts=2, base_delay_s=0.01,
                                            max_delay_s=0.02, jitter_s=0.0))
    with pytest.raises(RateLimitError) as exc_info:
        client.get("/v1/limited")
    assert exc_info.value.retry_after_s == 3.0


@respx.mock
def test_retry_after_is_clamped_to_max():
    respx.get(f"{BASE_URL}/v1/limited").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "999999"})
    )
    client = make_client(retry=RetryConfig(max_attempts=1, base_delay_s=0.01,
                                            max_delay_s=0.02, jitter_s=0.0,
                                            max_retry_after_s=5.0))
    with pytest.raises(RateLimitError) as exc_info:
        client.get("/v1/limited")
    assert exc_info.value.retry_after_s == 5.0


# -- circuit breaker (unchanged behavior, still covered) -----------------

@respx.mock
def test_circuit_breaker_opens_after_threshold_and_blocks_calls():
    respx.get(f"{BASE_URL}/v1/down").mock(return_value=httpx.Response(503))
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_s=10)
    client = make_client(
        retry=RetryConfig(max_attempts=1, base_delay_s=0.01, max_delay_s=0.01, jitter_s=0.0),
        circuit_breaker=breaker,
    )

    with pytest.raises(ServerError):
        client.get("/v1/down")
    with pytest.raises(ServerError):
        client.get("/v1/down")

    assert breaker.state == CircuitState.OPEN

    with pytest.raises(CircuitOpenError):
        client.get("/v1/down")


@respx.mock
def test_circuit_breaker_half_opens_and_recovers():
    route = respx.get(f"{BASE_URL}/v1/recovering")
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(503),
        httpx.Response(200, json={"ok": True}),
    ]
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_s=0.05)
    client = make_client(
        retry=RetryConfig(max_attempts=1, base_delay_s=0.01, max_delay_s=0.01, jitter_s=0.0),
        circuit_breaker=breaker,
    )

    with pytest.raises(ServerError):
        client.get("/v1/recovering")
    with pytest.raises(ServerError):
        client.get("/v1/recovering")
    assert breaker.state == CircuitState.OPEN

    import time
    time.sleep(0.06)  # let reset_timeout_s elapse
    assert breaker.state == CircuitState.HALF_OPEN

    result = client.get("/v1/recovering")
    assert result == {"ok": True}
    assert breaker.state == CircuitState.CLOSED


# -- oauth2 --------------------------------------------------------------

@respx.mock
def test_oauth2_token_is_fetched_and_reused():
    token_route = respx.post(f"{BASE_URL}/oauth/token").mock(
        return_value=httpx.Response(200, json={"access_token": "abc123", "expires_in": 300})
    )
    data_route = respx.get(f"{BASE_URL}/v1/secure").mock(
        return_value=httpx.Response(200, json={"secure": True})
    )

    config = ResilientClientConfig(
        base_url=BASE_URL,
        oauth2=OAuth2Config(
            token_url=f"{BASE_URL}/oauth/token",
            client_id="my-client",
            client_secret="my-secret",
        ),
        retry=RetryConfig(max_attempts=1),
    )
    client = ResilientAPIClient(config)

    client.get("/v1/secure")
    client.get("/v1/secure")  # second call should reuse cached token

    assert token_route.call_count == 1, "token should be cached, not re-fetched every call"
    assert data_route.call_count == 2
    sent_auth_header = data_route.calls[0].request.headers["Authorization"]
    assert sent_auth_header == "Bearer abc123"


# -- config validation -----------------------------------------------------

def test_rejects_missing_mtls_cert_file():
    config = ResilientClientConfig(
        base_url=BASE_URL,
        mtls=MTLSConfig(cert_path="/does/not/exist.crt", key_path="/does/not/exist.key"),
    )
    with pytest.raises(ConfigError) as exc_info:
        ResilientAPIClient(config)
    assert "cert_path" in str(exc_info.value)
    assert "key_path" in str(exc_info.value)


def test_rejects_incomplete_oauth2_config():
    config = ResilientClientConfig(
        base_url=BASE_URL,
        oauth2=OAuth2Config(token_url="", client_id="", client_secret="secret"),
    )
    with pytest.raises(ConfigError) as exc_info:
        ResilientAPIClient(config)
    assert "token_url" in str(exc_info.value)
    assert "client_id" in str(exc_info.value)


def test_rejects_nonsensical_retry_config():
    config = ResilientClientConfig(
        base_url=BASE_URL,
        retry=RetryConfig(max_attempts=0, base_delay_s=1.0, max_delay_s=0.5),
    )
    with pytest.raises(ConfigError) as exc_info:
        ResilientAPIClient(config)
    message = str(exc_info.value)
    assert "max_attempts" in message
    assert "max_delay_s" in message


def test_rejects_non_https_base_url():
    config = ResilientClientConfig(base_url="http://api.example-partner.com")
    with pytest.raises(ConfigError) as exc_info:
        ResilientAPIClient(config)
    assert "https://" in str(exc_info.value)


def test_allows_http_localhost_for_local_testing():
    # Should not raise: localhost is exempt from the https:// requirement
    # so the client can be exercised against a local mock server.
    config = ResilientClientConfig(base_url="http://localhost:8080/api")
    client = ResilientAPIClient(config)
    client.close()


def test_valid_config_constructs_without_error():
    config = ResilientClientConfig(base_url=BASE_URL)
    client = ResilientAPIClient(config)
    client.close()


# -- retry safety: only replay when it cannot repeat a side effect --------------

NO_DELAY = RetryConfig(max_attempts=3, base_delay_s=0.01, max_delay_s=0.02, jitter_s=0.0)


@respx.mock
def test_post_5xx_is_not_retried_and_flags_unknown_outcome():
    route = respx.post(f"{BASE_URL}/v1/pay").mock(return_value=httpx.Response(503))
    client = make_client(retry=NO_DELAY)

    with pytest.raises(ServerError) as exc_info:
        client.post("/v1/pay", json={"amount": 1})

    assert route.call_count == 1
    assert exc_info.value.outcome_unknown is True


@respx.mock
def test_post_5xx_with_idempotency_key_is_retried_and_sends_the_key():
    route = respx.post(f"{BASE_URL}/v1/pay")
    route.side_effect = [httpx.Response(503), httpx.Response(200, json={"ok": True})]
    client = make_client(retry=NO_DELAY)

    result = client.post("/v1/pay", json={"amount": 1}, idempotency_key="order-42")

    assert result == {"ok": True}
    assert route.call_count == 2
    for call in route.calls:
        assert call.request.headers["Idempotency-Key"] == "order-42"


@respx.mock
def test_idempotency_header_name_is_configurable():
    route = respx.post(f"{BASE_URL}/v1/pay").mock(return_value=httpx.Response(200, json={}))
    client = make_client(idempotency_header="X-Request-Id")

    client.post("/v1/pay", idempotency_key="abc")

    assert route.calls[0].request.headers["X-Request-Id"] == "abc"
    assert "Idempotency-Key" not in route.calls[0].request.headers


@respx.mock
def test_post_429_is_always_retried_because_the_server_declined_it():
    route = respx.post(f"{BASE_URL}/v1/pay")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"ok": True}),
    ]
    client = make_client(retry=NO_DELAY)

    assert client.post("/v1/pay", json={}) == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_post_connect_error_is_retried_because_nothing_was_sent():
    route = respx.post(f"{BASE_URL}/v1/pay")
    route.side_effect = [httpx.ConnectError("refused"), httpx.Response(200, json={"ok": True})]
    client = make_client(retry=NO_DELAY)

    assert client.post("/v1/pay", json={}) == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_post_read_timeout_is_not_retried_and_flags_unknown_outcome():
    route = respx.post(f"{BASE_URL}/v1/pay").mock(side_effect=httpx.ReadTimeout("slow"))
    client = make_client(retry=NO_DELAY)

    with pytest.raises(RetryExhaustedError) as exc_info:
        client.post("/v1/pay", json={})

    assert route.call_count == 1
    assert exc_info.value.outcome_unknown is True


@respx.mock
def test_get_read_timeout_is_retried_because_get_is_idempotent():
    route = respx.get(f"{BASE_URL}/v1/read")
    route.side_effect = [httpx.ReadTimeout("slow"), httpx.Response(200, json={"ok": True})]
    client = make_client(retry=NO_DELAY)

    assert client.get("/v1/read") == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_put_and_delete_5xx_are_retried_because_they_are_idempotent():
    put_route = respx.put(f"{BASE_URL}/v1/item")
    put_route.side_effect = [httpx.Response(503), httpx.Response(200, json={"ok": True})]
    delete_route = respx.delete(f"{BASE_URL}/v1/item")
    delete_route.side_effect = [httpx.Response(502), httpx.Response(200, json={"ok": True})]
    client = make_client(retry=NO_DELAY)

    assert client.put("/v1/item", json={}) == {"ok": True}
    assert client.delete("/v1/item") == {"ok": True}
    assert put_route.call_count == 2
    assert delete_route.call_count == 2


@respx.mock
def test_patch_is_not_retried_by_default():
    route = respx.patch(f"{BASE_URL}/v1/item").mock(return_value=httpx.Response(503))
    client = make_client(retry=NO_DELAY)

    with pytest.raises(ServerError) as exc_info:
        client.patch("/v1/item", json={})

    assert exc_info.value.outcome_unknown is True

    assert route.call_count == 1


@respx.mock
def test_exhausted_get_does_not_flag_unknown_outcome():
    respx.get(f"{BASE_URL}/v1/down").mock(return_value=httpx.Response(503))
    client = make_client(retry=NO_DELAY)

    with pytest.raises(ServerError) as exc_info:
        client.get("/v1/down")

    assert exc_info.value.outcome_unknown is False


@respx.mock
def test_retryable_methods_can_be_widened_for_a_partner_that_deduplicates():
    route = respx.post(f"{BASE_URL}/v1/pay")
    route.side_effect = [httpx.Response(503), httpx.Response(200, json={"ok": True})]
    retry = RetryConfig(
        max_attempts=3, base_delay_s=0.01, max_delay_s=0.02, jitter_s=0.0,
        retryable_methods=("GET", "POST"),
    )
    client = make_client(retry=retry)

    assert client.post("/v1/pay", json={}) == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_unsafe_post_failure_still_counts_toward_the_breaker_exactly_once():
    respx.post(f"{BASE_URL}/v1/pay").mock(return_value=httpx.Response(503))
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_s=10)
    client = make_client(retry=NO_DELAY, circuit_breaker=breaker)

    with pytest.raises(ServerError):
        client.post("/v1/pay", json={})
    assert breaker.state == CircuitState.CLOSED
    with pytest.raises(ServerError):
        client.post("/v1/pay", json={})
    assert breaker.state == CircuitState.OPEN


def test_rejects_empty_idempotency_header():
    config = ResilientClientConfig(base_url=BASE_URL, idempotency_header="  ")

    with pytest.raises(ConfigError) as exc_info:
        ResilientAPIClient(config)

    assert "idempotency_header" in str(exc_info.value)
