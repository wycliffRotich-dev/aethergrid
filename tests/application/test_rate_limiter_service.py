import time

import pytest

from app.application.services.rate_limiter_service import (
    RateLimiterService,
)
from app.domain.exceptions.rate_limit_exceeded_error import (
    RateLimitExceededError,
)
from app.domain.value_objects.api_key_id import ApiKeyId


def test_check_allows_requests_up_to_capacity() -> None:
    limiter = RateLimiterService(
        capacity=5,
        refill_rate_per_second=1.0,
    )

    api_key_id = ApiKeyId.new()

    for _ in range(5):
        limiter.check(api_key_id)


def test_check_raises_once_bucket_is_exhausted() -> None:
    """
    A fresh bucket starts full (capacity tokens). Refill rate is
    kept low enough that the elapsed time of the calls
    themselves cannot refill a whole extra token before the
    bucket is exhausted, so the 6th call in a row against a
    5-token bucket must be rejected.
    """
    limiter = RateLimiterService(
        capacity=5,
        refill_rate_per_second=0.001,
    )

    api_key_id = ApiKeyId.new()

    for _ in range(5):
        limiter.check(api_key_id)

    with pytest.raises(RateLimitExceededError) as exc_info:
        limiter.check(api_key_id)

    assert exc_info.value.api_key_id == api_key_id
    assert exc_info.value.retry_after_seconds > 0


def test_check_refills_tokens_over_time() -> None:
    """
    A caller that has exhausted its bucket regains capacity as
    time passes, at refill_rate_per_second. A high refill rate
    is used so this is verifiable with a short, non-flaky sleep
    rather than waiting close to a full second in the test
    suite.
    """
    limiter = RateLimiterService(
        capacity=1,
        refill_rate_per_second=1000.0,
    )

    api_key_id = ApiKeyId.new()

    limiter.check(api_key_id)

    with pytest.raises(RateLimitExceededError):
        limiter.check(api_key_id)

    time.sleep(0.05)

    limiter.check(api_key_id)


def test_check_tracks_buckets_independently_per_api_key() -> None:
    """
    Exhausting one caller's bucket must not affect a different
    caller -- each ApiKey.id gets its own bucket (see ADR 0021:
    limiting is per authenticated identity, not global).
    """
    limiter = RateLimiterService(
        capacity=1,
        refill_rate_per_second=0.001,
    )

    first_caller = ApiKeyId.new()
    second_caller = ApiKeyId.new()

    limiter.check(first_caller)

    with pytest.raises(RateLimitExceededError):
        limiter.check(first_caller)

    limiter.check(second_caller)


def test_constructor_rejects_non_positive_capacity() -> None:
    with pytest.raises(ValueError):
        RateLimiterService(
            capacity=0,
            refill_rate_per_second=1.0,
        )


def test_constructor_rejects_non_positive_refill_rate() -> None:
    with pytest.raises(ValueError):
        RateLimiterService(
            capacity=5,
            refill_rate_per_second=0.0,
        )
