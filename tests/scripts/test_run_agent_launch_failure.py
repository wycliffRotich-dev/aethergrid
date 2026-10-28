from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from scripts.run_agent import run_job


def test_a_job_whose_command_cannot_start_is_reported_as_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    ADR 0081. The command does not exist. The agent must report the
    job as failed under the lease it held, and must not die with the
    job still leased to it.
    """
    monkeypatch.setattr("scripts.run_agent.RENEWAL_INTERVAL_SECONDS", 3600)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    client = httpx.Client(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )
    job = {
        "id": "job-1",
        "command": [str(tmp_path / "no-such-binary")],
        "lease_id": "lease-abc",
        "execution_timeout_seconds": 30,
    }

    run_job(client, "worker-1", job)

    assert [r.url.path for r in requests] == [
        "/workers/worker-1/jobs/job-1/start",
        "/workers/worker-1/jobs/job-1/fail",
    ]
    assert json.loads(requests[-1].content) == {
        "exit_code": None,
        "lease_id": "lease-abc",
    }
