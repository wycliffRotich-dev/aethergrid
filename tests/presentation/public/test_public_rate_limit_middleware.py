"""
ADR 0103, decisions 5, 6 and 7. The limiter is a middleware of the public
app, so every request is counted: known routes, unknown paths, refused
methods and CORS preflights. A refusal is a fixed 429 that names no client
and no limit, and it still carries the CORS header the browser needs to
read it.
"""

from __future__ import annotations

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from app.application.public_rate_limiter import AnonymousRateLimiter
from app.presentation.public.app import create_public_app
from app.presentation.public.settings import PublicSettings
from tests.support.public_app import FakePublicReader

ORIGIN = "https://demo.example.org"
URL = "postgresql://aethergrid_public@db.internal:5432/aethergrid"
PASSWORD_FILE = "/run/secrets/public_db_password"
SOCKET = "203.0.113.7"
PREFLIGHT = {"Origin": ORIGIN, "Access-Control-Request-Method": "GET"}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_settings(hops: int) -> PublicSettings:
    return PublicSettings.from_environment(
        {
            "AETHERGRID_PUBLIC_ALLOWED_ORIGIN": ORIGIN,
            "AETHERGRID_PUBLIC_DATABASE_URL": URL,
            "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE": PASSWORD_FILE,
            "AETHERGRID_PUBLIC_TRUSTED_PROXY_HOPS": str(hops),
        }
    )


def make_client(
    clock: FakeClock,
    *,
    hops: int = 0,
    client_capacity: int = 2,
    socket: str = SOCKET,
) -> TestClient:
    limiter = AnonymousRateLimiter(
        client_capacity=client_capacity,
        client_refill_per_second=1.0,
        global_capacity=1000,
        global_refill_per_second=1000.0,
        max_clients=100,
        clock=clock,
    )
    app = create_public_app(make_settings(hops), limiter=limiter, reader=FakePublicReader())

    return TestClient(app, client=(socket, 50000))


def forwarded(value: str) -> dict[str, str]:
    return {"X-Forwarded-For": value}


class TestCounting:
    def test_requests_within_the_limit_pass(self) -> None:
        client = make_client(FakeClock())

        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz").status_code == 200

    def test_the_request_after_the_limit_is_refused(self) -> None:
        client = make_client(FakeClock())
        client.get("/healthz")
        client.get("/healthz")

        assert client.get("/healthz").status_code == 429

    def test_the_health_route_is_not_exempt(self) -> None:
        client = make_client(FakeClock(), client_capacity=1)

        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz").status_code == 429

    def test_unknown_paths_are_counted(self) -> None:
        client = make_client(FakeClock())

        assert client.get("/nodes").status_code == 404
        assert client.get("/docs").status_code == 404
        assert client.get("/healthz").status_code == 429

    def test_refused_methods_are_counted(self) -> None:
        client = make_client(FakeClock())

        assert client.post("/healthz").status_code == 405
        assert client.delete("/healthz").status_code == 405
        assert client.get("/healthz").status_code == 429

    def test_cors_preflights_are_counted(self) -> None:
        client = make_client(FakeClock())

        assert client.options("/healthz", headers=PREFLIGHT).status_code == 200
        assert client.options("/healthz", headers=PREFLIGHT).status_code == 200
        assert client.options("/healthz", headers=PREFLIGHT).status_code == 429
        assert client.get("/healthz").status_code == 429

    def test_the_default_limiter_is_active(self) -> None:
        client = TestClient(create_public_app(make_settings(0), reader=FakePublicReader()))

        statuses = [client.get("/healthz").status_code for _ in range(60)]

        assert statuses[:20] == [200] * 20
        assert 429 in statuses

    def test_startup_and_shutdown_are_not_limited(self) -> None:
        with TestClient(create_public_app(make_settings(0), reader=FakePublicReader())) as client:
            assert client.get("/healthz").status_code == 200


class TestRefusal:
    def test_the_body_is_fixed(self) -> None:
        client = make_client(FakeClock())
        client.get("/healthz")
        client.get("/healthz")

        refused = client.get("/healthz")

        assert refused.status_code == 429
        assert refused.json() == {"detail": "Too many requests."}

    def test_the_retry_after_header_is_a_whole_number_of_seconds(self) -> None:
        client = make_client(FakeClock())
        client.get("/healthz")
        client.get("/healthz")

        value = client.get("/healthz").headers["retry-after"]

        assert value.isdigit()
        assert int(value) >= 1

    def test_the_retry_after_header_is_honest(self) -> None:
        clock = FakeClock()
        client = make_client(clock)
        client.get("/healthz")
        client.get("/healthz")
        refused = client.get("/healthz")

        clock.advance(int(refused.headers["retry-after"]))

        assert client.get("/healthz").status_code == 200

    def test_the_response_names_no_client_and_no_limit(self) -> None:
        client = make_client(FakeClock())
        client.get("/healthz")
        client.get("/healthz")

        refused = client.get("/healthz")

        assert set(refused.headers.keys()) == {
            "content-type",
            "content-length",
            "retry-after",
        }
        assert SOCKET not in refused.text

    def test_the_same_refusal_is_given_for_every_path(self) -> None:
        client = make_client(FakeClock())
        client.get("/healthz")
        client.get("/healthz")

        first = client.get("/healthz")
        second = client.get("/nodes")

        assert first.status_code == second.status_code == 429
        assert first.content == second.content


class TestCorsOnRefusal:
    def test_a_refusal_carries_the_configured_origin(self) -> None:
        client = make_client(FakeClock())
        client.get("/healthz", headers={"Origin": ORIGIN})
        client.get("/healthz", headers={"Origin": ORIGIN})

        refused = client.get("/healthz", headers={"Origin": ORIGIN})

        assert refused.status_code == 429
        assert refused.headers["access-control-allow-origin"] == ORIGIN

    def test_a_refusal_agrees_with_what_the_cors_middleware_sends(self) -> None:
        client = make_client(FakeClock())
        admitted = client.get("/healthz", headers={"Origin": ORIGIN})
        client.get("/healthz", headers={"Origin": ORIGIN})
        refused = client.get("/healthz", headers={"Origin": ORIGIN})

        assert (
            refused.headers["access-control-allow-origin"]
            == admitted.headers["access-control-allow-origin"]
        )
        assert refused.headers.get("vary") == admitted.headers.get("vary")

    def test_another_origin_gets_no_allow_origin_header(self) -> None:
        client = make_client(FakeClock())
        other = {"Origin": "https://evil.example"}
        client.get("/healthz", headers=other)
        client.get("/healthz", headers=other)

        refused = client.get("/healthz", headers=other)

        assert refused.status_code == 429
        assert "access-control-allow-origin" not in refused.headers

    def test_a_refusal_never_allows_credentials(self) -> None:
        client = make_client(FakeClock())
        client.get("/healthz", headers={"Origin": ORIGIN})
        client.get("/healthz", headers={"Origin": ORIGIN})

        refused = client.get("/healthz", headers={"Origin": ORIGIN})

        assert "access-control-allow-credentials" not in refused.headers

    def test_a_refused_preflight_carries_the_configured_origin(self) -> None:
        client = make_client(FakeClock())
        client.options("/healthz", headers=PREFLIGHT)
        client.options("/healthz", headers=PREFLIGHT)

        refused = client.options("/healthz", headers=PREFLIGHT)

        assert refused.status_code == 429
        assert refused.headers["access-control-allow-origin"] == ORIGIN


class TestWhoIsCounted:
    def test_with_no_proxy_the_header_is_ignored(self) -> None:
        client = make_client(FakeClock(), hops=0)

        assert client.get("/healthz", headers=forwarded("1.1.1.1")).status_code == 200
        assert client.get("/healthz", headers=forwarded("2.2.2.2")).status_code == 200
        assert client.get("/healthz", headers=forwarded("3.3.3.3")).status_code == 429

    def test_the_socket_address_is_the_client_with_no_proxy(self) -> None:
        clock = FakeClock()
        first = make_client(clock, socket="203.0.113.7")
        second = make_client(clock, socket="203.0.113.8")

        first.get("/healthz")
        first.get("/healthz")

        assert first.get("/healthz").status_code == 429
        # A separate app has its own limiter, so this checks only the key.
        assert second.get("/healthz").status_code == 200

    def test_with_one_proxy_the_rightmost_entry_is_the_client(self) -> None:
        client = make_client(FakeClock(), hops=1)

        assert client.get("/healthz", headers=forwarded("6.6.6.6, 10.0.0.1")).status_code == 200
        assert client.get("/healthz", headers=forwarded("7.7.7.7, 10.0.0.1")).status_code == 200
        assert client.get("/healthz", headers=forwarded("8.8.8.8, 10.0.0.1")).status_code == 429

    def test_a_different_rightmost_entry_is_a_different_client(self) -> None:
        client = make_client(FakeClock(), hops=1)
        client.get("/healthz", headers=forwarded("1.1.1.1, 10.0.0.1"))
        client.get("/healthz", headers=forwarded("1.1.1.1, 10.0.0.1"))

        assert client.get("/healthz", headers=forwarded("1.1.1.1, 10.0.0.2")).status_code == 200

    def test_repeated_header_lines_are_read_as_one_list(self) -> None:
        client = make_client(FakeClock(), hops=1)

        def request(caller_line: str) -> int:
            return client.get(
                "/healthz",
                headers=[
                    ("x-forwarded-for", caller_line),
                    ("x-forwarded-for", "10.0.0.1"),
                ],
            ).status_code

        assert request("6.6.6.6") == 200
        assert request("7.7.7.7") == 200
        assert request("8.8.8.8") == 429

    def test_with_one_proxy_and_no_header_the_socket_address_is_used(self) -> None:
        client = make_client(FakeClock(), hops=1)

        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz").status_code == 429

    def test_rotating_inside_one_ipv6_slash_64_is_one_client(self) -> None:
        client = make_client(FakeClock(), hops=1)

        assert client.get("/healthz", headers=forwarded("2001:db8:1:2::1")).status_code == 200
        assert client.get("/healthz", headers=forwarded("2001:db8:1:2::2")).status_code == 200
        assert client.get("/healthz", headers=forwarded("2001:db8:1:2:ffff::3")).status_code == 429

    @pytest.mark.parametrize("junk", ["unknown", "garbage-1", "garbage-2", "999.1.1.1"])
    def test_garbage_in_the_header_shares_one_client(self, junk: str) -> None:
        client = make_client(FakeClock(), hops=1)
        client.get("/healthz", headers=forwarded("junk-a"))
        client.get("/healthz", headers=forwarded("junk-b"))

        assert client.get("/healthz", headers=forwarded(junk)).status_code == 429


class TestWebSockets:
    def test_a_websocket_handshake_is_counted(self) -> None:
        client = make_client(FakeClock())

        for _ in range(2):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect("/healthz"):
                    pass

        assert client.get("/healthz").status_code == 429

    def test_a_refused_websocket_handshake_is_closed_with_1013(self) -> None:
        client = make_client(FakeClock())
        client.get("/healthz")
        client.get("/healthz")

        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect("/healthz"):
                pass

        assert caught.value.code == 1013


class TestTheHeaderIsActuallyRead:
    """
    Each test ends with a client that the header makes different. If the
    hops setting were ignored every request would be counted against the
    socket address and that last request would be refused.
    """

    def test_a_different_proxy_entry_is_admitted_across_header_lines(self) -> None:
        client = make_client(FakeClock(), hops=1)

        def request(caller_line: str, proxy_line: str) -> int:
            return client.get(
                "/healthz",
                headers=[
                    ("x-forwarded-for", caller_line),
                    ("x-forwarded-for", proxy_line),
                ],
            ).status_code

        assert request("6.6.6.6", "10.0.0.1") == 200
        assert request("7.7.7.7", "10.0.0.1") == 200
        assert request("8.8.8.8", "10.0.0.1") == 429
        assert request("8.8.8.8", "10.0.0.2") == 200

    def test_a_different_ipv6_slash_64_is_admitted(self) -> None:
        client = make_client(FakeClock(), hops=1)
        client.get("/healthz", headers=forwarded("2001:db8:1:2::1"))
        client.get("/healthz", headers=forwarded("2001:db8:1:2::2"))

        other = client.get("/healthz", headers=forwarded("2001:db8:1:3::1"))

        assert other.status_code == 200

    def test_a_real_address_is_admitted_after_garbage_is_refused(self) -> None:
        client = make_client(FakeClock(), hops=1)
        client.get("/healthz", headers=forwarded("junk-a"))
        client.get("/healthz", headers=forwarded("junk-b"))

        assert client.get("/healthz", headers=forwarded("junk-c")).status_code == 429
        assert client.get("/healthz", headers=forwarded("203.0.113.50")).status_code == 200
