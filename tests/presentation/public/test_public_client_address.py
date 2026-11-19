"""
ADR 0103, decision 5. The address that is counted for a request.

With no trusted proxy the socket address is used and X-Forwarded-For is
ignored. With N trusted proxies the Nth entry from the right is used,
because the entries on the right were written by proxies the operator
controls and the caller can write only the left. Every selected value is
untrusted text and reaches client_key, so a bad one gets the shared key.
"""

from __future__ import annotations

import pytest

from app.application.public_rate_limiter import SHARED_CLIENT_KEY, client_key
from app.presentation.public.client_address import select_client_address

SOCKET = "198.51.100.1"


def pick(lines: list[str], hops: int, socket: str | None = SOCKET) -> str | None:
    return select_client_address(socket, lines, hops)


class TestNoTrustedProxy:
    def test_the_socket_address_is_used(self) -> None:
        assert pick([], 0) == SOCKET

    def test_the_header_is_ignored(self) -> None:
        assert pick(["203.0.113.9"], 0) == SOCKET

    def test_a_forged_header_changes_nothing(self) -> None:
        assert pick(["6.6.6.6, 7.7.7.7", "8.8.8.8"], 0) == SOCKET

    def test_a_missing_socket_address_stays_missing(self) -> None:
        assert pick(["203.0.113.9"], 0, socket=None) is None


class TestNthFromTheRight:
    def test_one_hop_takes_the_last_entry(self) -> None:
        assert pick(["203.0.113.9"], 1) == "203.0.113.9"

    def test_one_hop_with_a_chain_takes_the_rightmost(self) -> None:
        assert pick(["6.6.6.6, 10.0.0.5, 203.0.113.9"], 1) == "203.0.113.9"

    def test_two_hops_take_the_second_from_the_right(self) -> None:
        assert pick(["6.6.6.6, 203.0.113.9, 10.0.0.5"], 2) == "203.0.113.9"

    def test_exactly_as_many_entries_as_hops_takes_the_leftmost(self) -> None:
        assert pick(["203.0.113.9, 10.0.0.5"], 2) == "203.0.113.9"

    def test_entries_the_caller_prepended_never_change_the_result(self) -> None:
        genuine = "203.0.113.9"
        forged = ", ".join(f"6.6.6.{n}" for n in range(1, 200))

        assert pick([f"{forged}, {genuine}"], 1) == genuine
        assert pick([f"9.9.9.9, {genuine}"], 1) == genuine
        assert pick([genuine], 1) == genuine

    def test_whitespace_around_an_entry_is_removed(self) -> None:
        assert pick(["6.6.6.6 ,   203.0.113.9  "], 1) == "203.0.113.9"

    def test_the_socket_address_is_not_counted_as_an_entry(self) -> None:
        assert pick(["203.0.113.9, 10.0.0.5"], 1) == "10.0.0.5"


class TestRepeatedHeaderLines:
    def test_lines_are_joined_in_order_before_counting(self) -> None:
        # A proxy that adds its own line leaves the caller's line first.
        assert pick(["6.6.6.6", "203.0.113.9"], 1) == "203.0.113.9"
        assert pick(["6.6.6.6", "203.0.113.9"], 2) == "6.6.6.6"

    def test_a_line_with_several_entries_is_split(self) -> None:
        assert pick(["1.1.1.1, 2.2.2.2", "3.3.3.3"], 2) == "2.2.2.2"
        assert pick(["1.1.1.1, 2.2.2.2", "3.3.3.3"], 3) == "1.1.1.1"

    def test_the_first_line_alone_never_decides_the_result(self) -> None:
        assert pick(["6.6.6.6", "203.0.113.9"], 1) != "6.6.6.6"


class TestTooFewEntries:
    def test_no_header_falls_back_to_the_socket_address(self) -> None:
        assert pick([], 1) == SOCKET

    def test_fewer_entries_than_hops_falls_back_to_the_socket_address(self) -> None:
        assert pick(["203.0.113.9"], 2) == SOCKET
        assert pick(["1.1.1.1, 2.2.2.2"], 3) == SOCKET

    def test_the_fallback_keeps_a_missing_socket_address_missing(self) -> None:
        assert pick([], 1, socket=None) is None


class TestEmptyEntries:
    def test_an_empty_entry_counts_as_an_entry(self) -> None:
        assert pick(["1.1.1.1,,203.0.113.9"], 3) == "1.1.1.1"

    def test_a_selected_empty_entry_gets_the_shared_key(self) -> None:
        selected = pick(["1.1.1.1,,203.0.113.9"], 2)

        assert client_key(selected) == SHARED_CLIENT_KEY

    def test_an_empty_header_value_is_one_empty_entry(self) -> None:
        assert pick([""], 1) == ""
        assert client_key(pick([""], 1)) == SHARED_CLIENT_KEY


class TestPortsAndBrackets:
    def test_an_ipv4_port_is_removed(self) -> None:
        assert pick(["203.0.113.9:443"], 1) == "203.0.113.9"

    def test_a_bracketed_ipv6_address_loses_its_brackets(self) -> None:
        assert pick(["[2001:db8::1]"], 1) == "2001:db8::1"

    def test_a_bracketed_ipv6_address_loses_its_port(self) -> None:
        assert pick(["[2001:db8::1]:443"], 1) == "2001:db8::1"

    def test_a_bare_ipv6_address_is_left_alone(self) -> None:
        assert pick(["2001:db8::1"], 1) == "2001:db8::1"

    def test_the_port_form_and_the_bare_form_are_one_client(self) -> None:
        assert client_key(pick(["203.0.113.9:443"], 1)) == client_key("203.0.113.9")
        assert client_key(pick(["[2001:db8::1]:443"], 1)) == client_key(
            "2001:db8::1"
        )

    @pytest.mark.parametrize(
        "entry",
        [
            "203.0.113.9:",
            "203.0.113.9:abc",
            "203.0.113.9:99999",
            "203.0.113.9:65536",
            "203.0.113.9:-1",
            "203.0.113.9:+1",
            "203.0.113.9:1 2",
            "203.0.113.9:\u0663",
            "203.0.113.9:443:443",
            "[2001:db8::1]:abc",
            "[2001:db8::1]:",
            "[2001:db8::1",
            "2001:db8::1]",
            "[203.0.113.9]:443",
            "[[2001:db8::1]]",
        ],
    )
    def test_a_malformed_port_form_gets_the_shared_key(self, entry: str) -> None:
        assert client_key(pick([entry], 1)) == SHARED_CLIENT_KEY

    def test_the_largest_port_is_accepted(self) -> None:
        assert pick(["203.0.113.9:65535"], 1) == "203.0.113.9"


class TestUntrustedText:
    @pytest.mark.parametrize(
        "entry",
        ["unknown", "garbage", "999.1.1.1", "_hidden", "for=203.0.113.9", "\x00"],
    )
    def test_a_selected_value_that_is_not_an_address_gets_the_shared_key(
        self, entry: str
    ) -> None:
        assert client_key(pick([entry], 1)) == SHARED_CLIENT_KEY

    def test_a_flood_of_garbage_entries_cannot_create_keys(self) -> None:
        keys = {client_key(pick([f"junk-{n}"], 1)) for n in range(1_000)}

        assert keys == {SHARED_CLIENT_KEY}


class TestHopsAreChecked:
    @pytest.mark.parametrize("hops", [-1, 6, 100])
    def test_a_count_outside_zero_to_five_is_refused(self, hops: int) -> None:
        with pytest.raises(ValueError):
            pick(["203.0.113.9"], hops)
