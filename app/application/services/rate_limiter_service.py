from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.domain.exceptions.rate_limit_exceeded_error import (
    RateLimitExceededError,
)
from app.domain.value_objects.api_key_id import ApiKeyId


@dataclass(slots=True)
class _Bucket:
    """
    A single caller's token bucket.

    tokens is a float, not an int, since refill happens
    continuously based on elapsed time rather than in whole
    increments on a timer.
    """

    tokens: float
    last_refilled_at: float


class RateLimiterService:
    """
    Enforces a per-ApiKey token bucket rate limit, in-memory,
    local to this process (see ADR 0021).

    One bucket per ApiKey.id, created lazily on first use.
    capacity is both the bucket's maximum size and its burst
    allowance: a caller that has been idle can spend up to
    capacity requests immediately before being throttled to
    refill_rate_per_second thereafter.

    Guarded by a single lock rather than one lock per bucket.
    Requests are not the hot path this system optimizes for
    (job scheduling and lease renewal are); a single lock keeps
    this correct and simple rather than introducing per-key
    locking for a contention scenario that does not exist here.
    """

    def __init__(
        self,
        capacity: int,
        refill_rate_per_second: float,
    ) -> None:
        if capacity <= 0:
            raise ValueError(
                "capacity must be a positive number of tokens."
            )

        if refill_rate_per_second <= 0:
            raise ValueError(
                "refill_rate_per_second must be positive."
            )

        self._capacity = capacity
        self._refill_rate_per_second = refill_rate_per_second
        self._buckets: dict[ApiKeyId, _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, api_key_id: ApiKeyId) -> None:
        """
        Consume one token for this caller.

        Raises RateLimitExceededError if none are available.
        Does nothing (and consumes a token) on success; callers
        that do not catch the exception may proceed.
        """
        now = time.monotonic()

        with self._lock:
            bucket = self._buckets.get(api_key_id)

            if bucket is None:
                bucket = _Bucket(
                    tokens=float(self._capacity),
                    last_refilled_at=now,
                )
                self._buckets[api_key_id] = bucket

            elapsed = now - bucket.last_refilled_at
            bucket.tokens = min(
                float(self._capacity),
                bucket.tokens
                + elapsed * self._refill_rate_per_second,
            )
            bucket.last_refilled_at = now

            if bucket.tokens < 1.0:
                tokens_needed = 1.0 - bucket.tokens
                retry_after_seconds = (
                    tokens_needed / self._refill_rate_per_second
                )
                raise RateLimitExceededError(
                    api_key_id,
                    retry_after_seconds,
                )

            bucket.tokens -= 1.0
