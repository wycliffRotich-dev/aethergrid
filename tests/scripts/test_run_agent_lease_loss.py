from __future__ import annotations

import time

import httpx
import pytest

from scripts.run_agent import run_job


def test_run_job_kills_subprocess_when_lease_is_lost_mid_execution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Integration-level regression test for the gap ADR 0044
    explicitly deferred: "This does not stop a job whose lease
    was lost. The lost-lease flag is only checked after the
    subprocess exits, so a reclaimed job can still run to
    completion on the agent."

    Unlike test_job_execution_service.py's lease_lost_event
    tests, which prove JobExecutionService.execute() reacts
    correctly to an event that's already set, this test proves
    the real wiring: run_job()'s renewal thread detecting a
    lost lease over a mocked HTTP call actually reaches and
    preempts a real, currently-running subprocess -- not just
    that the post-execution check at the end of run_job() (line
    ~505) skips reporting the outcome, which was already true
    before this fix and is insufficient on its own.

    RENEWAL_INTERVAL_SECONDS is patched down from its real
    value (10s, one third of the 30s default lease duration)
    so this test proves the wiring in well under a second
    rather than waiting on real fleet timing.
    """
    monkeypatch.setattr(
        "scripts.run_agent.RENEWAL_INTERVAL_SECONDS",
        0.05,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/start"):
            return httpx.Response(200, json={})

        # Every other call in this flow is a lease renewal.
        # Returning 409 immediately means the very first
        # renewal attempt reports the lease as lost -- the
        # same lease-lost signal already proven correct by
        # test_renew_lease_returns_lease_lost_on_409.
        return httpx.Response(
            409,
            json={"detail": "lease already lost"},
        )

    client = httpx.Client(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )

    job = {
        "id": "job-1",
        "command": ["python3", "-c", "import time; time.sleep(5)"],
        "lease_id": "lease-abc",
        "execution_timeout_seconds": 30,
    }

    start = time.monotonic()
    run_job(client, "worker-1", job)
    duration = time.monotonic() - start

    # The command sleeps for 5 real seconds. Before this fix,
    # lost_lease was only checked after execute() returned, so
    # the subprocess would run the full 5s regardless of when
    # the lease was actually lost. If the wiring is correct,
    # the renewal thread detects the loss almost immediately
    # (patched interval: 0.05s) and preempts the subprocess
    # well within JobExecutionService's default 5s termination
    # grace period -- nowhere near the command's own 5s sleep.
    assert duration < 3

    captured = capsys.readouterr()
    assert "lease lost during execution" in captured.out
