from __future__ import annotations

import json

import httpx

from scripts.run_agent import renew_lease


def test_renew_lease_sends_lease_id_in_request_body() -> None:
    """
    Regression test: renew_lease() must send lease_id in the
    request body, matching RenewLeaseRequest (ADR 0038). Before
    this was fixed, the call sent no body at all, so every
    renewal returned 422 and was misreported as a lost lease.
    """
    captured_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content))
        return httpx.Response(200, json={"running_job": None})

    client = httpx.Client(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )

    renew_lease(client, "worker-1", "lease-abc")

    assert captured_body == {"lease_id": "lease-abc"}


def test_renew_lease_returns_lease_held_true_with_job_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"running_job": {"status": "RUNNING"}},
        )

    client = httpx.Client(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )

    lease_ok, job_status = renew_lease(client, "worker-1", "lease-abc")

    assert lease_ok is True
    assert job_status == "RUNNING"


def test_renew_lease_returns_lease_held_true_with_no_running_job() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"running_job": None})

    client = httpx.Client(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )

    lease_ok, job_status = renew_lease(client, "worker-1", "lease-abc")

    assert lease_ok is True
    assert job_status is None


def test_renew_lease_returns_lease_lost_on_409() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "lease already lost"})

    client = httpx.Client(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )

    lease_ok, job_status = renew_lease(client, "worker-1", "lease-abc")

    assert lease_ok is False
    assert job_status is None
