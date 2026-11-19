"""
Anonymous rate limiting for the public app (ADR 0103).

Standard library only. The limiter of ADR 0021 is keyed on an ApiKeyId and
is not reused here.
"""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

# The one key for a missing or unparseable address. It is not the text form
# of any IPv4 address or IPv6 /64 key, so no real address can collide with it.
SHARED_CLIENT_KEY = "unattributed"

# First values, not measured (ADR 0103, decision 8).
CLIENT_CAPACITY = 20
CLIENT_REFILL_PER_SECOND = 2.0
GLOBAL_CAPACITY = 200
GLOBAL_REFILL_PER_SECOND = 50.0
MAX_CLIENTS = 10_000

_MAX_ADDRESS_LENGTH = 64
_IPV6_PREFIX_BYTES = 8
_MIN_RETRY_AFTER_SECONDS = 1


def client_key(address: str | None) -> str:
    """
    The key under which a caller is counted (ADR 0103, decision 4).

    An IPv4 address is its own key. An IPv6 address is keyed by its first
    64 bits, so a caller who rotates inside one /64 stays one client. An
    IPv4 mapped IPv6 address is keyed as its IPv4 address. A missing or
    unparseable address gets one shared key, so garbage cannot create keys.
    """
    if address is None:
        return SHARED_CLIENT_KEY

    text = address.strip()

    if not text or len(text) > _MAX_ADDRESS_LENGTH:
        return SHARED_CLIENT_KEY

    try:
        parsed = ipaddress.ip_address(text)
    except ValueError:
        return SHARED_CLIENT_KEY

    if isinstance(parsed, ipaddress.IPv6Address):
        mapped = parsed.ipv4_mapped

        if mapped is not None:
            return str(mapped)

        prefix = parsed.packed[:_IPV6_PREFIX_BYTES]
        network = ipaddress.IPv6Address(
            prefix + bytes(16 - _IPV6_PREFIX_BYTES)
        )
        return f"{network}/64"

    return str(parsed)


class AnonymousRateLimitExceededError(Exception):
    """
    Raised when a request is refused.

    The message is fixed and names no client and no limit (decision 6).
    retry_after_seconds is a whole number of seconds, at least 1.
    """

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Too many requests.")
        self.retry_after_seconds = retry_after_seconds


@dataclass(slots=True)
class _Bucket:
    tokens: float
    last_refilled_at: float


def _refill(
    bucket: _Bucket, now: float, capacity: int, rate_per_second: float
) -> None:
    # Never negative: a clock that appears to step back adds nothing.
    elapsed = max(0.0, now - bucket.last_refilled_at)
    bucket.tokens = min(
        float(capacity), bucket.tokens + elapsed * rate_per_second
    )
    bucket.last_refilled_at = now


def _seconds_until_one_token(
    bucket: _Bucket, rate_per_second: float
) -> float:
    if bucket.tokens >= 1.0:
        return 0.0

    return (1.0 - bucket.tokens) / rate_per_second


class AnonymousRateLimiter:
    """
    A per client bucket and one global bucket, in memory and local to this
    process (ADR 0103).

    A request passes only when both buckets hold a token. Both are checked
    and consumed under one lock, and a refusal consumes nothing. The table
    of clients holds at most max_clients entries and drops the least
    recently used one when it is full, so a caller cannot grow it without
    bound. The global bucket bounds the total load however clients rotate.

    clock returns seconds and defaults to time.monotonic. It is read inside
    the lock, so a thread that waited for the lock never refills with a
    time older than the one a previous thread already applied.
    """

    def __init__(
        self,
        *,
        client_capacity: int = CLIENT_CAPACITY,
        client_refill_per_second: float = CLIENT_REFILL_PER_SECOND,
        global_capacity: int = GLOBAL_CAPACITY,
        global_refill_per_second: float = GLOBAL_REFILL_PER_SECOND,
        max_clients: int = MAX_CLIENTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if client_capacity <= 0:
            raise ValueError("client_capacity must be positive.")

        if client_refill_per_second <= 0:
            raise ValueError("client_refill_per_second must be positive.")

        if global_capacity <= 0:
            raise ValueError("global_capacity must be positive.")

        if global_refill_per_second <= 0:
            raise ValueError("global_refill_per_second must be positive.")

        if max_clients <= 0:
            raise ValueError("max_clients must be positive.")

        self._client_capacity = client_capacity
        self._client_refill_per_second = client_refill_per_second
        self._global_capacity = global_capacity
        self._global_refill_per_second = global_refill_per_second
        self._max_clients = max_clients
        self._clock = clock
        self._lock = threading.Lock()
        self._global: _Bucket | None = None
        self._clients: OrderedDict[str, _Bucket] = OrderedDict()

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def check(self, address: str | None) -> None:
        """
        Consume one token from the caller's bucket and the global bucket.

        Raises AnonymousRateLimitExceededError, consuming nothing, when
        either bucket is empty.
        """
        key = client_key(address)

        with self._lock:
            now = self._clock()

            if self._global is None:
                self._global = _Bucket(
                    tokens=float(self._global_capacity),
                    last_refilled_at=now,
                )
            else:
                _refill(
                    self._global,
                    now,
                    self._global_capacity,
                    self._global_refill_per_second,
                )

            client = self._clients.get(key)

            if client is None:
                is_new = True
                client = _Bucket(
                    tokens=float(self._client_capacity),
                    last_refilled_at=now,
                )
            else:
                is_new = False
                self._clients.move_to_end(key)
                _refill(
                    client,
                    now,
                    self._client_capacity,
                    self._client_refill_per_second,
                )

            wait = max(
                _seconds_until_one_token(
                    self._global, self._global_refill_per_second
                ),
                _seconds_until_one_token(
                    client, self._client_refill_per_second
                ),
            )

            if wait > 0.0:
                raise AnonymousRateLimitExceededError(
                    max(_MIN_RETRY_AFTER_SECONDS, math.ceil(wait))
                )

            self._global.tokens -= 1.0
            client.tokens -= 1.0

            if is_new:
                self._clients[key] = client

                if len(self._clients) > self._max_clients:
                    self._clients.popitem(last=False)
