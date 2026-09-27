"""
Resilient client for talking to third-party (e.g. government) HTTP APIs.

Design goals, based on the real-world constraints of integrating with
government / regulated infrastructure:

  * Auth: supports mTLS (client cert + key) and/or OAuth2 client-credentials,
    since both patterns are common with government gateways.
  * Resilience: exponential backoff with jitter on transient failures,
    plus a circuit breaker so we stop hammering a dead endpoint and fail
    fast instead of piling up latency.
  * Observability: every request/retry/circuit-state-change is logged
    with structured fields so it's debuggable when their side misbehaves.
  * No surprises: explicit timeouts everywhere, explicit exceptions,
    nothing swallowed silently.

This is intentionally dependency-light: only `httpx` is required at runtime.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger("gov_api_client")


# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------

class GovAPIError(Exception):
    """Base class for all errors raised by GovAPIClient."""


class AuthError(GovAPIError):
    """Raised when authentication/token acquisition fails."""


class CircuitOpenError(GovAPIError):
    """Raised when a call is rejected because the circuit breaker is open."""


class RetryExhaustedError(GovAPIError):
    """Raised when all retry attempts are used up without success."""

    def __init__(self, message: str, last_exception: Exception | None = None):
        super().__init__(message)
        self.last_exception = last_exception


# --------------------------------------------------------------------------
# Circuit breaker
# --------------------------------------------------------------------------

class CircuitState(Enum):
    CLOSED = "closed"        # normal operation
    OPEN = "open"            # failing fast, not calling downstream
    HALF_OPEN = "half_open"  # letting one trial request through


@dataclass
class CircuitBreaker:
    """
    Simple circuit breaker.

    - Starts CLOSED.
    - After `failure_threshold` consecutive failures, trips to OPEN.
    - After `reset_timeout_s`, moves to HALF_OPEN and allows one trial call.
    - A successful trial call closes the circuit again.
    - A failed trial call reopens it and restarts the timeout.
    """

    failure_threshold: int = 5
    reset_timeout_s: float = 30.0

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _consecutive_failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self.reset_timeout_s:
                logger.info("circuit_breaker: OPEN -> HALF_OPEN (reset timeout elapsed)")
                self._state = CircuitState.HALF_OPEN
        return self._state

    def before_call(self) -> None:
        if self.state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"Circuit is open; failing fast (retry after "
                f"{self.reset_timeout_s:.0f}s from last trip)"
            )

    def on_success(self) -> None:
        if self._state != CircuitState.CLOSED:
            logger.info("circuit_breaker: %s -> CLOSED (call succeeded)", self._state.value)
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = None

    def on_failure(self) -> None:
        self._consecutive_failures += 1
        if self.state == CircuitState.HALF_OPEN:
            logger.warning("circuit_breaker: HALF_OPEN -> OPEN (trial call failed)")
            self._trip()
            return
        if self._consecutive_failures >= self.failure_threshold:
            logger.warning(
                "circuit_breaker: CLOSED -> OPEN (%d consecutive failures)",
                self._consecutive_failures,
            )
            self._trip()

    def _trip(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

@dataclass
class RetryConfig:
    max_attempts: int = 4
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0
    jitter_s: float = 0.25
    # Status codes worth retrying (transient/server-side); 4xx besides 429
    # are treated as non-retryable client errors.
    retryable_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)


@dataclass
class MTLSConfig:
    cert_path: str
    key_path: str
    ca_bundle_path: str | None = None  # verify against their CA if provided


@dataclass
class OAuth2Config:
    token_url: str
    client_id: str
    client_secret: str
    scope: str | None = None
    # refresh a bit before actual expiry to avoid using a token that
    # expires mid-flight
    expiry_skew_s: float = 30.0


@dataclass
class GovAPIClientConfig:
    base_url: str
    timeout_s: float = 10.0
    mtls: MTLSConfig | None = None
    oauth2: OAuth2Config | None = None
    retry: RetryConfig = field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    default_headers: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------

class GovAPIClient:
    """
    Usage:

        config = GovAPIClientConfig(
            base_url="https://sandbox.example.gov/api",
            mtls=MTLSConfig(cert_path="client.crt", key_path="client.key"),
            oauth2=OAuth2Config(
                token_url="https://sandbox.example.gov/oauth/token",
                client_id="...",
                client_secret="...",
            ),
        )
        client = GovAPIClient(config)
        data = client.get("/v1/citizens/12345")
    """

    def __init__(self, config: GovAPIClientConfig, transport: httpx.BaseTransport | None = None):
        self.config = config
        self._token: str | None = None
        self._token_expiry: float = 0.0

        cert = None
        if config.mtls:
            cert = (config.mtls.cert_path, config.mtls.key_path)

        verify: Any = True
        if config.mtls and config.mtls.ca_bundle_path:
            verify = config.mtls.ca_bundle_path

        self._http = httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout_s,
            cert=cert,
            verify=verify,
            headers=config.default_headers,
            transport=transport,  # injectable for tests / mocking
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GovAPIClient:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # -- public HTTP verbs ---------------------------------------------

    def get(self, path: str, **kwargs: Any) -> Any:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self._request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self._request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self._request("DELETE", path, **kwargs)

    # -- auth ------------------------------------------------------------

    def _get_access_token(self) -> str:
        assert self.config.oauth2 is not None
        now = time.monotonic()
        if self._token and now < self._token_expiry:
            return self._token

        oauth = self.config.oauth2
        logger.info("gov_api_client: fetching new OAuth2 token")
        try:
            resp = self._http.post(
                oauth.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": oauth.client_id,
                    "client_secret": oauth.client_secret,
                    **({"scope": oauth.scope} if oauth.scope else {}),
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AuthError(f"Failed to acquire OAuth2 token: {exc}") from exc

        token = payload.get("access_token")
        if not token:
            raise AuthError("Token endpoint response missing 'access_token'")

        expires_in = float(payload.get("expires_in", 300))
        self._token = token
        self._token_expiry = now + max(expires_in - oauth.expiry_skew_s, 0)
        return token

    # -- core request path with retry + circuit breaker -------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        breaker = self.config.circuit_breaker
        retry_cfg = self.config.retry

        breaker.before_call()

        headers = kwargs.pop("headers", {}) or {}
        if self.config.oauth2:
            headers["Authorization"] = f"Bearer {self._get_access_token()}"

        last_exc: Exception | None = None

        for attempt in range(1, retry_cfg.max_attempts + 1):
            try:
                logger.info("gov_api_client: %s %s (attempt %d/%d)",
                            method, path, attempt, retry_cfg.max_attempts)
                resp = self._http.request(method, path, headers=headers, **kwargs)

                if resp.status_code in retry_cfg.retryable_statuses:
                    raise httpx.HTTPStatusError(
                        f"Retryable status {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )

                resp.raise_for_status()
                breaker.on_success()
                return resp.json() if resp.content else None

            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                is_last_attempt = attempt == retry_cfg.max_attempts
                logger.warning(
                    "gov_api_client: attempt %d/%d failed: %s",
                    attempt, retry_cfg.max_attempts, exc,
                )
                if is_last_attempt:
                    break

                delay = min(
                    retry_cfg.base_delay_s * (2 ** (attempt - 1)),
                    retry_cfg.max_delay_s,
                )
                delay += random.uniform(0, retry_cfg.jitter_s)
                time.sleep(delay)

        # The whole request (all attempts) counts as a single failure from
        # the circuit breaker's point of view — it trips on consecutive
        # *requests* failing, not consecutive low-level attempts.
        breaker.on_failure()
        raise RetryExhaustedError(
            f"{method} {path} failed after {retry_cfg.max_attempts} attempts",
            last_exception=last_exc,
        )
