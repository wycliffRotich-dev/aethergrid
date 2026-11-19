"""
Tests for the anonymous limiter's buckets (ADR 0103, decisions 2, 3, 6, 8).

The limiter takes a clock, so every refill here is exact and nothing sleeps.
Retry values use powers of two where a division has to come out exact.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from app.application.public_rate_limiter import (
    CLIENT_CAPACITY,
    CLIENT_REFILL_PER_SECOND,
    GLOBAL_CAPACITY,
    GLOBAL_REFILL_PER_SECOND,
    MAX_CLIENTS,
    AnonymousRateLimiter,
    AnonymousRateLimitExceededError,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_limiter(
    clock: FakeClock,
    *,
    client_capacity: int = 5,
    client_refill_per_second: float = 1.0,
    global_capacity: int = 1000,
    global_refill_per_second: float = 1000.0,
    max_clients: int = 100,
) -> AnonymousRateLimiter:
    return AnonymousRateLimiter(
        client_capacity=client_capacity,
        client_refill_per_second=client_refill_per_second,
        global_capacity=global_capacity,
        global_refill_per_second=global_refill_per_second,
        max_clients=max_clients,
        clock=clock,
    )


def admitted(limiter: AnonymousRateLimiter, address: str | None) -> bool:
    try:
        limiter.check(address)
    except AnonymousRateLimitExceededError:
        return False

    return True


def retry_after(limiter: AnonymousRateLimiter, address: str | None) -> int:
    with pytest.raises(AnonymousRateLimitExceededError) as caught:
        limiter.check(address)

    return caught.value.retry_after_seconds


class TestClientBucket:
    def test_a_client_spends_its_capacity_then_is_refused(self) -> None:
        limiter = make_limiter(FakeClock(), client_capacity=3)

        results = [admitted(limiter, "203.0.113.7") for _ in range(4)]

        assert results == [True, True, True, False]

    def test_clients_have_separate_buckets(self) -> None:
        limiter = make_limiter(FakeClock(), client_capacity=1)

        assert admitted(limiter, "203.0.113.7")
        assert not admitted(limiter, "203.0.113.7")
        assert admitted(limiter, "203.0.113.8")

    def test_a_client_refills_over_time(self) -> None:
        clock = FakeClock()
        limiter = make_limiter(
            clock, client_capacity=2, client_refill_per_second=1.0
        )

        assert admitted(limiter, "203.0.113.7")
        assert admitted(limiter, "203.0.113.7")
        assert not admitted(limiter, "203.0.113.7")

        clock.advance(1.0)

        assert admitted(limiter, "203.0.113.7")
        assert not admitted(limiter, "203.0.113.7")

    def test_refill_never_exceeds_capacity(self) -> None:
        clock = FakeClock()
        limiter = make_limiter(clock, client_capacity=2)

        assert admitted(limiter, "203.0.113.7")

        clock.advance(1_000.0)

        results = [admitted(limiter, "203.0.113.7") for _ in range(3)]

        assert results == [True, True, False]

    def test_one_ipv6_slash_64_shares_one_bucket(self) -> None:
        limiter = make_limiter(FakeClock(), client_capacity=2)

        assert admitted(limiter, "2001:db8:1:2::1")
        assert admitted(limiter, "2001:db8:1:2::2")
        assert not admitted(limiter, "2001:db8:1:2:ffff::3")

    def test_unparseable_addresses_share_one_bucket(self) -> None:
        limiter = make_limiter(FakeClock(), client_capacity=2)

        assert admitted(limiter, "garbage-1")
        assert admitted(limiter, "garbage-2")
        assert not admitted(limiter, "garbage-3")
        assert not admitted(limiter, None)


class TestGlobalBucket:
    def test_the_global_bucket_bounds_the_total_across_clients(self) -> None:
        limiter = make_limiter(
            FakeClock(),
            global_capacity=3,
            global_refill_per_second=0.001,
        )

        results = [admitted(limiter, f"203.0.113.{n}") for n in range(1, 6)]

        assert results == [True, True, True, False, False]

    def test_the_global_bucket_refills_over_time(self) -> None:
        clock = FakeClock()
        limiter = make_limiter(
            clock, global_capacity=1, global_refill_per_second=1.0
        )

        assert admitted(limiter, "203.0.113.1")
        assert not admitted(limiter, "203.0.113.2")

        clock.advance(1.0)

        assert admitted(limiter, "203.0.113.2")

    def test_a_refused_client_cannot_drain_the_global_bucket(self) -> None:
        limiter = make_limiter(
            FakeClock(),
            client_capacity=1,
            client_refill_per_second=0.001,
            global_capacity=5,
            global_refill_per_second=0.001,
        )

        assert admitted(limiter, "203.0.113.1")

        for _ in range(100):
            assert not admitted(limiter, "203.0.113.1")

        # One global token went to the first request. Four are left.
        others = [admitted(limiter, f"203.0.113.{n}") for n in range(2, 7)]

        assert others == [True, True, True, True, False]

    def test_a_global_refusal_does_not_cost_an_existing_client(self) -> None:
        clock = FakeClock()
        limiter = make_limiter(
            clock,
            client_capacity=2,
            client_refill_per_second=0.01,
            global_capacity=2,
            global_refill_per_second=1.0,
        )

        assert admitted(limiter, "203.0.113.1")
        assert admitted(limiter, "203.0.113.2")
        # The global bucket is empty. The client bucket of .1 still holds one.
        assert not admitted(limiter, "203.0.113.1")

        clock.advance(1.0)

        assert admitted(limiter, "203.0.113.1")

    def test_a_global_refusal_does_not_cost_a_new_client(self) -> None:
        clock = FakeClock()
        limiter = make_limiter(
            clock,
            client_capacity=1,
            client_refill_per_second=0.01,
            global_capacity=2,
            global_refill_per_second=1.0,
        )

        assert admitted(limiter, "203.0.113.1")
        assert admitted(limiter, "203.0.113.2")
        assert not admitted(limiter, "203.0.113.3")

        clock.advance(1.0)

        assert admitted(limiter, "203.0.113.3")


class TestRetryAfter:
    def test_it_is_a_whole_number_of_seconds(self) -> None:
        limiter = make_limiter(
            FakeClock(), client_capacity=1, client_refill_per_second=0.4
        )
        limiter.check("203.0.113.7")

        value = retry_after(limiter, "203.0.113.7")

        assert isinstance(value, int)

    def test_it_rounds_a_fractional_wait_up(self) -> None:
        limiter = make_limiter(
            FakeClock(), client_capacity=1, client_refill_per_second=0.4
        )
        limiter.check("203.0.113.7")

        # One token at 0.4 a second is 2.5 seconds.
        assert retry_after(limiter, "203.0.113.7") == 3

    def test_it_is_never_below_one_second(self) -> None:
        limiter = make_limiter(
            FakeClock(), client_capacity=1, client_refill_per_second=4.0
        )
        limiter.check("203.0.113.7")

        # One token at 4 a second is 0.25 seconds.
        assert retry_after(limiter, "203.0.113.7") == 1

    def test_it_counts_the_refill_already_earned(self) -> None:
        clock = FakeClock()
        limiter = make_limiter(
            clock, client_capacity=1, client_refill_per_second=0.25
        )
        limiter.check("203.0.113.7")

        clock.advance(1.0)

        # 0.25 tokens held, 0.75 missing, at 0.25 a second is 3 seconds.
        assert retry_after(limiter, "203.0.113.7") == 3

    def test_a_global_only_refusal_uses_the_global_wait(self) -> None:
        limiter = make_limiter(
            FakeClock(),
            client_capacity=5,
            global_capacity=1,
            global_refill_per_second=0.5,
        )
        limiter.check("203.0.113.1")

        assert retry_after(limiter, "203.0.113.2") == 2

    def test_when_both_are_empty_the_larger_wait_is_used_global(self) -> None:
        limiter = make_limiter(
            FakeClock(),
            client_capacity=1,
            client_refill_per_second=0.5,
            global_capacity=1,
            global_refill_per_second=0.1,
        )
        limiter.check("203.0.113.7")

        # Client wait 2 seconds, global wait 10 seconds.
        assert retry_after(limiter, "203.0.113.7") == 10

    def test_when_both_are_empty_the_larger_wait_is_used_client(self) -> None:
        limiter = make_limiter(
            FakeClock(),
            client_capacity=1,
            client_refill_per_second=0.25,
            global_capacity=1,
            global_refill_per_second=1.0,
        )
        limiter.check("203.0.113.7")

        # Client wait 4 seconds, global wait 1 second.
        assert retry_after(limiter, "203.0.113.7") == 4


class TestBoundedTable:
    def test_the_table_never_holds_more_than_max_clients(self) -> None:
        limiter = make_limiter(
            FakeClock(), global_capacity=10_000, max_clients=10
        )

        for n in range(500):
            limiter.check(f"10.0.{n // 256}.{n % 256}")

            assert limiter.client_count <= 10

        assert limiter.client_count == 10

    def test_the_least_recently_used_client_is_dropped(self) -> None:
        limiter = make_limiter(
            FakeClock(), client_capacity=1, max_clients=2
        )

        assert admitted(limiter, "192.0.2.1")
        assert admitted(limiter, "192.0.2.2")
        # Using .1 again makes .2 the least recently used.
        assert not admitted(limiter, "192.0.2.1")
        # A third client arrives, so .2 is dropped.
        assert admitted(limiter, "192.0.2.3")

        # .1 was kept, and its bucket is still empty.
        assert not admitted(limiter, "192.0.2.1")
        # .2 was dropped, so it starts again with a full bucket.
        assert admitted(limiter, "192.0.2.2")

    def test_a_new_client_refused_globally_is_not_added(self) -> None:
        limiter = make_limiter(
            FakeClock(),
            global_capacity=1,
            global_refill_per_second=0.001,
            max_clients=10,
        )

        assert admitted(limiter, "203.0.113.1")
        assert limiter.client_count == 1

        for n in range(2, 102):
            assert not admitted(limiter, f"203.0.113.{n}")

        assert limiter.client_count == 1

    def test_a_flood_cannot_evict_a_client_that_was_admitted(self) -> None:
        limiter = make_limiter(
            FakeClock(),
            client_capacity=1,
            global_capacity=2,
            global_refill_per_second=0.001,
            max_clients=2,
        )

        assert admitted(limiter, "192.0.2.1")
        assert admitted(limiter, "192.0.2.2")

        for n in range(3, 200):
            assert not admitted(limiter, f"192.0.2.{n}")

        assert limiter.client_count == 2


class TestErrorAndConfiguration:
    def test_the_error_names_no_client(self) -> None:
        limiter = make_limiter(FakeClock(), client_capacity=1)
        limiter.check("203.0.113.7")

        with pytest.raises(AnonymousRateLimitExceededError) as caught:
            limiter.check("203.0.113.7")

        assert "203.0.113.7" not in str(caught.value)
        assert "203.0.113.7" not in repr(caught.value)

    def test_the_limits_are_the_named_constants_of_decision_8(self) -> None:
        assert CLIENT_CAPACITY == 20
        assert CLIENT_REFILL_PER_SECOND == 2.0
        assert GLOBAL_CAPACITY == 200
        assert GLOBAL_REFILL_PER_SECOND == 50.0
        assert MAX_CLIENTS == 10_000

    def test_the_default_limiter_admits_the_client_capacity(self) -> None:
        limiter = AnonymousRateLimiter(clock=FakeClock())

        results = [admitted(limiter, "203.0.113.7") for _ in range(21)]

        assert results == [True] * 20 + [False]

    @pytest.mark.parametrize(
        "field",
        [
            "client_capacity",
            "client_refill_per_second",
            "global_capacity",
            "global_refill_per_second",
            "max_clients",
        ],
    )
    @pytest.mark.parametrize("bad", [0, -1])
    def test_a_non_positive_setting_is_refused(
        self, field: str, bad: int
    ) -> None:
        settings: dict[str, Any] = {
            "client_capacity": 5,
            "client_refill_per_second": 1.0,
            "global_capacity": 50,
            "global_refill_per_second": 10.0,
            "max_clients": 10,
        }
        settings[field] = bad

        with pytest.raises(ValueError):
            AnonymousRateLimiter(clock=FakeClock(), **settings)


class TestConcurrency:
    def test_threads_never_admit_more_than_one_clients_capacity(self) -> None:
        limiter = make_limiter(
            FakeClock(), client_capacity=100, global_capacity=10_000
        )
        threads_count = 8
        calls_each = 50
        counts = [0] * threads_count
        barrier = threading.Barrier(threads_count)

        def worker(index: int) -> None:
            barrier.wait()

            for _ in range(calls_each):
                if admitted(limiter, "203.0.113.7"):
                    counts[index] += 1

        threads = [
            threading.Thread(target=worker, args=(i,))
            for i in range(threads_count)
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        assert sum(counts) == 100

    def test_threads_never_admit_more_than_the_global_capacity(self) -> None:
        limiter = make_limiter(
            FakeClock(),
            client_capacity=100,
            global_capacity=100,
            global_refill_per_second=0.001,
        )
        threads_count = 8
        calls_each = 50
        counts = [0] * threads_count
        barrier = threading.Barrier(threads_count)

        def worker(index: int) -> None:
            barrier.wait()

            for _ in range(calls_each):
                if admitted(limiter, f"203.0.113.{index + 1}"):
                    counts[index] += 1

        threads = [
            threading.Thread(target=worker, args=(i,))
            for i in range(threads_count)
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        assert sum(counts) == 100
