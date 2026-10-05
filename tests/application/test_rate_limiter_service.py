import pytest

from app.application.services.rate_limiter_service import (
    RateLimiterService,
)
from app.domain.exceptions.rate_limit_exceeded_error import (
    RateLimitExceededError,
)
from app.domain.value_objects.api_key_id import ApiKeyId


class _FakeClock:
    """
    A clock that only moves when the test moves it, so refill
    is exact and no test depends on how fast the runner is.
    """

    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


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
    time passes, at refill_rate_per_second. The clock is
    controlled, so half a token must not be enough and a whole
    token must be, with no sleeping and no timing margin.
    """
    clock = _FakeClock()
    limiter = RateLimiterService(
        capacity=1,
        refill_rate_per_second=1.0,
        clock=clock,
    )

    api_key_id = ApiKeyId.new()

    limiter.check(api_key_id)

    with pytest.raises(RateLimitExceededError):
        limiter.check(api_key_id)

    clock.advance(0.5)

    with pytest.raises(RateLimitExceededError):
        limiter.check(api_key_id)

    clock.advance(0.5)

    limiter.check(api_key_id)


def test_check_reports_exact_retry_after_seconds() -> None:
    """
    With an empty bucket and a refill rate of 2 tokens per
    second, one token takes exactly half a second to arrive.
    """
    clock = _FakeClock()
    limiter = RateLimiterService(
        capacity=1,
        refill_rate_per_second=2.0,
        clock=clock,
    )

    api_key_id = ApiKeyId.new()

    limiter.check(api_key_id)

    with pytest.raises(RateLimitExceededError) as exc_info:
        limiter.check(api_key_id)

    assert exc_info.value.retry_after_seconds == 0.5


def test_check_never_refills_beyond_capacity() -> None:
    """
    A long idle period restores the bucket to capacity and no
    further, so the burst allowance stays capacity requests.
    """
    clock = _FakeClock()
    limiter = RateLimiterService(
        capacity=2,
        refill_rate_per_second=1.0,
        clock=clock,
    )

    api_key_id = ApiKeyId.new()

    limiter.check(api_key_id)
    limiter.check(api_key_id)

    clock.advance(100.0)

    limiter.check(api_key_id)
    limiter.check(api_key_id)

    with pytest.raises(RateLimitExceededError):
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
