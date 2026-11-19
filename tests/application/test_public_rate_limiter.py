"""
Tests for the anonymous rate limiter (ADR 0103).

The client key decides who is counted, so it is tested first and hardest.
"""

from __future__ import annotations

import pytest

from app.application.public_rate_limiter import SHARED_CLIENT_KEY, client_key


class TestClientKey:
    def test_an_ipv4_address_is_its_own_key(self) -> None:
        assert client_key("203.0.113.7") == "203.0.113.7"

    def test_two_ipv4_addresses_have_different_keys(self) -> None:
        assert client_key("203.0.113.7") != client_key("203.0.113.8")

    def test_addresses_in_one_ipv6_slash_64_share_a_key(self) -> None:
        first = client_key("2001:db8:1:2:aaaa:bbbb:cccc:dddd")
        second = client_key("2001:db8:1:2::1")

        assert first == second

    def test_addresses_in_different_ipv6_slash_64s_do_not_share_a_key(
        self,
    ) -> None:
        assert client_key("2001:db8:1:2::1") != client_key("2001:db8:1:3::1")

    def test_a_difference_only_in_the_last_64_bits_is_one_client(self) -> None:
        keys = {client_key(f"2001:db8:1:2::{n:x}") for n in range(1, 500)}

        assert len(keys) == 1

    def test_an_ipv6_key_is_never_equal_to_an_ipv4_key(self) -> None:
        assert client_key("2001:db8:1:2::1") != client_key("203.0.113.7")

    def test_an_ipv4_mapped_ipv6_address_is_keyed_as_its_ipv4_address(
        self,
    ) -> None:
        assert client_key("::ffff:203.0.113.7") == client_key("203.0.113.7")

    def test_an_ipv6_zone_id_does_not_change_the_key(self) -> None:
        assert client_key("fe80::1%eth0") == client_key("fe80::1")

    def test_surrounding_whitespace_does_not_change_the_key(self) -> None:
        assert client_key("  203.0.113.7 ") == client_key("203.0.113.7")

    @pytest.mark.parametrize(
        "garbage",
        [
            None,
            "",
            " ",
            "garbage",
            "999.1.1.1",
            "1.2.3.4.5",
            "1.2.3.4, 5.6.7.8",
            "2001:db8::zz",
            "unknown",
            "\x00",
            "a" * 10_000,
        ],
    )
    def test_a_missing_or_unparseable_address_gets_the_shared_key(
        self, garbage: str | None
    ) -> None:
        assert client_key(garbage) == SHARED_CLIENT_KEY

    def test_garbage_cannot_create_new_keys(self) -> None:
        keys = {client_key(f"not-an-address-{n}") for n in range(1_000)}

        assert keys == {SHARED_CLIENT_KEY}

    def test_the_shared_key_is_not_the_key_of_any_real_address(self) -> None:
        for address in ("0.0.0.0", "127.0.0.1", "::", "::1", "203.0.113.7"):
            assert client_key(address) != SHARED_CLIENT_KEY
