"""
Resilient client for talking to third-party HTTP APIs that are slow,
rate-limited, or unreliable, government agencies, banks, legacy
enterprise systems, or any external system you don't control.

Design goals, based on the real-world constraints of integrating with
infrastructure you don't operate and can't fully see into:

  * Auth: supports mTLS (client cert + key) and/or OAuth2 client-credentials,
    since both patterns are common across regulated and enterprise gateways.
  * Resilience: exponential backoff with jitter on transient failures,
    honoring a server-supplied Retry-After header when present, plus a
    circuit breaker so we stop hammering a dead endpoint and fail fast
    instead of piling up latency.
  * Precise failure signaling: client mistakes (4xx), rate limiting (429),
    and server-side degradation (5xx/transport errors) are raised as
    distinct exception types, so callers can handle each appropriately
    instead of catching one generic error.
  * Fail loud, fail early: config is validated at construction time
    (cert paths exist, retry values are sane, OAuth2 fields are present)
    rather than failing confusingly on the first real request.
  * Observability: every request/retry/circuit-state-change is logged
    with structured fields so it's debuggable when their side misbehaves.

This is intentionally dependency-light: only `httpx` is required at runtime.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("resilient_api_client")


# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------

class ResilientAPIError(Exception):
    """Base class for all errors raised by ResilientAPIClient."""


class AuthError(ResilientAPIError):
    """Raised when authentication/token acquisition fails."""


class CircuitOpenError(ResilientAPIError):
    """Raised when a call is rejected because the circuit breaker is open."""


class ConfigError(ResilientAPIError):
    """Raised at construction time when ResilientClientConfig is invalid."""


class ClientError(ResilientAPIError):
    """
    Raised immediately (no retry) for a non-retryable 4xx response, e.g.
    404 or 400. This is a client-side mistake, not the endpoint being
    unhealthy, so it does not count as a circuit breaker failure.
    """

    def __init__(self, message: str, status_code: int, response_body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class RateLimitError(ResilientAPIError):
    """
    Raised when all retry attempts against a 429 response are exhausted.
    Carries the last Retry-After value seen, if the server sent one, so
    the caller can decide how long to wait before trying again.
    """

    def __init__(self, message: str, retry_after_s: float | None = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class ServerError(ResilientAPIError):
    """
    Raised when all retry attempts against a 5xx response are exhausted.
    Distinct from RetryExhaustedError so callers can tell "their server
    is down" apart from "the network itself is unreachable".
    """

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class RetryExhaustedError(ResilientAPIError):
    """
    Raised when all retry attempts are used up due to a transport-level
    error (timeout, connection refused, DNS failure) rather than an HTTP
    status code. Kept as a distinct type from ServerError/RateLimitError
    since there was no response at all to inspect.
    """

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

    Only server-side or transport-level failures count toward the
    threshold. A client-side mistake (4xx other than 429) never touches
    the breaker, since it says nothing about the endpoint's health.
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
    # Cap how long we'll ever honor a server-supplied Retry-After for,
    # so a misbehaving server can't stall a caller indefinitely.
    max_retry_after_s: float = 60.0


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
class ResilientClientConfig:
    base_url: str
    timeout_s: float = 10.0
    mtls: MTLSConfig | None = None
    oauth2: OAuth2Config | None = None
    retry: RetryConfig = field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    default_headers: dict[str, str] = field(default_factory=dict)


def _validate_config(config: ResilientClientConfig) -> None:
    """
    Raise ConfigError with every problem found, rather than the first
    one, so a misconfigured client fails once with a complete list
    instead of round-tripping through fixes one at a time.
    """
    errors: list[str] = []

    if not config.base_url:
        errors.append("base_url is required")
    elif not (config.base_url.startswith("https://") or "localhost" in config.base_url
              or "127.0.0.1" in config.base_url):
        errors.append(
            f"base_url should use https:// for a production endpoint, got: {config.base_url!r}"
        )

    if config.timeout_s <= 0:
        errors.append(f"timeout_s must be positive, got: {config.timeout_s}")

    if config.mtls:
        if not Path(config.mtls.cert_path).is_file():
            errors.append(f"mtls.cert_path not found: {config.mtls.cert_path!r}")
        if not Path(config.mtls.key_path).is_file():
            errors.append(f"mtls.key_path not found: {config.mtls.key_path!r}")
        if config.mtls.ca_bundle_path and not Path(config.mtls.ca_bundle_path).is_file():
            errors.append(f"mtls.ca_bundle_path not found: {config.mtls.ca_bundle_path!r}")

    if config.oauth2:
        if not config.oauth2.token_url:
            errors.append("oauth2.token_url is required")
        if not config.oauth2.client_id:
            errors.append("oauth2.client_id is required")
        if not config.oauth2.client_secret:
            errors.append("oauth2.client_secret is required")

    if config.retry.max_attempts < 1:
        errors.append(f"retry.max_attempts must be >= 1, got: {config.retry.max_attempts}")
    if config.retry.base_delay_s <= 0:
        errors.append(f"retry.base_delay_s must be positive, got: {config.retry.base_delay_s}")
    if config.retry.max_delay_s < config.retry.base_delay_s:
        errors.append(
            "retry.max_delay_s must be >= retry.base_delay_s, got: "
            f"max_delay_s={config.retry.max_delay_s}, base_delay_s={config.retry.base_delay_s}"
        )

    if config.circuit_breaker.failure_threshold < 1:
        errors.append(
            "circuit_breaker.failure_threshold must be >= 1, got: "
            f"{config.circuit_breaker.failure_threshold}"
        )
    if config.circuit_breaker.reset_timeout_s <= 0:
        errors.append(
            "circuit_breaker.reset_timeout_s must be positive, got: "
            f"{config.circuit_breaker.reset_timeout_s}"
        )

    if errors:
        bullet_list = "\n".join(f"  - {e}" for e in errors)
        raise ConfigError(f"Invalid ResilientClientConfig:\n{bullet_list}")


# --------------------------------------------------------------------------
# Retry-After parsing
# --------------------------------------------------------------------------

def _parse_retry_after(response: httpx.Response, max_retry_after_s: float) -> float | None:
    """
    Parse a Retry-After header per RFC 9110: either an integer number of
    seconds, or an HTTP-date. Returns None if the header is absent or
    unparseable. Result is clamped to [0, max_retry_after_s] so a
    misbehaving or malicious server can't stall a caller indefinitely.
    """
    raw = response.headers.get("Retry-After")
    if not raw:
        return None

    seconds: float | None = None
    try:
        seconds = float(raw)
    except ValueError:
        try:
            target_dt = parsedate_to_datetime(raw)
            seconds = (target_dt - target_dt.now(target_dt.tzinfo)).total_seconds()
        except (TypeError, ValueError):
            logger.warning("resilient_api_client: unparseable Retry-After header: %r", raw)
            return None

    if seconds is None:
        return None
    return max(0.0, min(seconds, max_retry_after_s))


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------

class ResilientAPIClient:
    """
    Usage:

        config = ResilientClientConfig(
            base_url="https://api.example-partner.com",
            mtls=MTLSConfig(cert_path="client.crt", key_path="client.key"),
            oauth2=OAuth2Config(
                token_url="https://api.example-partner.com/oauth/token",
                client_id="...",
                client_secret="...",
            ),
        )
        client = ResilientAPIClient(config)
        data = client.get("/v1/citizens/12345")

    Raises ConfigError immediately at construction if the config is
    invalid (bad cert paths, nonsensical retry values, missing OAuth2
    fields), rather than failing confusingly on first use.
    """

    def __init__(self, config: ResilientClientConfig, transport: httpx.BaseTransport | None = None):
        _validate_config(config)

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

    def __enter__(self) -> ResilientAPIClient:
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
        logger.info("resilient_api_client: fetching new OAuth2 token")
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

        last_transport_exc: Exception | None = None

        for attempt in range(1, retry_cfg.max_attempts + 1):
            try:
                logger.info("resilient_api_client: %s %s (attempt %d/%d)",
                            method, path, attempt, retry_cfg.max_attempts)
                resp = self._http.request(method, path, headers=headers, **kwargs)

            except httpx.TransportError as exc:
                last_transport_exc = exc
                is_last_attempt = attempt == retry_cfg.max_attempts
                logger.warning(
                    "resilient_api_client: attempt %d/%d transport error: %s",
                    attempt, retry_cfg.max_attempts, exc,
                )
                if is_last_attempt:
                    breaker.on_failure()
                    raise RetryExhaustedError(
                        f"{method} {path} failed after {retry_cfg.max_attempts} attempts "
                        "due to transport errors",
                        last_exception=last_transport_exc,
                    ) from exc
                self._sleep_before_retry(attempt, retry_cfg, retry_after_s=None)
                continue

            # Success.
            if resp.status_code < 400:
                breaker.on_success()
                return resp.json() if resp.content else None

            # Non-retryable client mistake: fail fast, don't touch the
            # breaker, since this says nothing about the endpoint's health.
            if resp.status_code not in retry_cfg.retryable_statuses:
                body = resp.text[:500] if resp.text else None
                raise ClientError(
                    f"{method} {path} returned non-retryable status {resp.status_code}",
                    status_code=resp.status_code,
                    response_body=body,
                )

            # Retryable (429 or 5xx): retry with backoff, honoring
            # Retry-After if the server sent one.
            is_last_attempt = attempt == retry_cfg.max_attempts
            logger.warning(
                "resilient_api_client: attempt %d/%d got retryable status %d",
                attempt, retry_cfg.max_attempts, resp.status_code,
            )
            if is_last_attempt:
                breaker.on_failure()
                if resp.status_code == 429:
                    retry_after = _parse_retry_after(resp, retry_cfg.max_retry_after_s)
                    raise RateLimitError(
                        f"{method} {path} still rate limited after "
                        f"{retry_cfg.max_attempts} attempts",
                        retry_after_s=retry_after,
                    )
                raise ServerError(
                    f"{method} {path} failed after {retry_cfg.max_attempts} attempts "
                    f"with status {resp.status_code}",
                    status_code=resp.status_code,
                )

            retry_after = _parse_retry_after(resp, retry_cfg.max_retry_after_s)
            self._sleep_before_retry(attempt, retry_cfg, retry_after_s=retry_after)

        # Unreachable in practice (the loop always returns or raises above),
        # kept only as a defensive fallback.
        raise RetryExhaustedError(
            f"{method} {path} failed after {retry_cfg.max_attempts} attempts",
            last_exception=last_transport_exc,
        )

    @staticmethod
    def _sleep_before_retry(
        attempt: int, retry_cfg: RetryConfig, retry_after_s: float | None
    ) -> None:
        if retry_after_s is not None:
            # The server told us explicitly how long to wait; honor that
            # over our own backoff guess.
            delay = retry_after_s
        else:
            delay = min(
                retry_cfg.base_delay_s * (2 ** (attempt - 1)),
                retry_cfg.max_delay_s,
            )
            delay += random.uniform(0, retry_cfg.jitter_s)
        time.sleep(delay)
