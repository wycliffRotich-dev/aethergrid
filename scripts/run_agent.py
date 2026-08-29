"""
Standalone worker agent process (ADR 0019).

Runs as a real, separate process, polling the API over HTTP for
work assigned to one worker, executing it as a real local
subprocess, and reporting the outcome back, the same way a real
compute node's agent would. This replaces two things that were
previously simulated:

  - Liveness: previously kept alive by the dashboard's browser-tab
    heartbeat (useWorkerHeartbeatKeeper.ts), which only worked
    while someone had a tab open. This agent heartbeats itself,
    for as long as it's actually running, nothing more.
  - Execution: previously happened synchronously, in-process,
    inside the API server's own background tick loop
    (ClusterTickService -> WorkerExecutionLoop). This agent
    executes on its own machine, over its own network hop, the
    same way a real distributed worker would.

Communicates exclusively over the existing authenticated REST
surface (ADR 0015), the same Authorization: Bearer mechanism the
frontend already uses. No new transport.

Job handoff is pull-based: this agent polls GET /workers/{id} on
its own interval rather than the server pushing work to it. See
ADR 0019's Alternatives Considered for why push was rejected.

Usage:
    export AETHERGRID_API_KEY="<key from scripts/issue_api_key.py>"
    python scripts/run_agent.py <node-id>

The node must already be registered (via the API or dashboard)
before starting an agent against it.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from datetime import timedelta

import httpx

from app.application.services.job_execution_service import (
    JobExecutionResult,
    JobExecutionService,
)
from app.domain.entities.lease import DEFAULT_LEASE_DURATION

POLL_INTERVAL_SECONDS = 5.0
HEARTBEAT_INTERVAL_SECONDS = 5.0
RENEWAL_INTERVAL_SECONDS = DEFAULT_LEASE_DURATION.total_seconds() / 3
API_BASE_URL = os.getenv(
    "AETHERGRID_API_URL",
    "http://localhost:8000",
)


class AgentError(Exception):
    """Raised for agent-level failures that should stop the run."""


def _client(api_key: str) -> httpx.Client:
    return httpx.Client(
        base_url=API_BASE_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10.0,
    )


def register_worker(client: httpx.Client, node_id: str) -> str:
    # managed_by="AGENT" marks this worker as owned by this
    # standalone process rather than ClusterTickService's in-process
    # execution loop, so the loop skips it and this agent is the
    # only thing that starts, executes, and reports outcomes for its
    # jobs (ADR 0019, issue #90). Every other caller of POST /workers
    # (e.g. the dashboard) omits this field and defaults to
    # "DASHBOARD", unaffected by this agent's existence.
    response = client.post(
        "/workers",
        json={"node_id": node_id, "managed_by": "AGENT"},
    )
    response.raise_for_status()
    worker_id = response.json()["id"]
    print(f"Registered worker {worker_id} against node {node_id}")
    return worker_id


def heartbeat_worker(client: httpx.Client, worker_id: str) -> None:
    response = client.post(
        f"/workers/{worker_id}/heartbeat",
    )
    response.raise_for_status()


def heartbeat_node(client: httpx.Client, node_id: str) -> None:
    response = client.post(
        f"/nodes/{node_id}/heartbeat",
    )
    response.raise_for_status()


def get_worker(client: httpx.Client, worker_id: str) -> dict:
    response = client.get(
        f"/workers/{worker_id}",
    )
    response.raise_for_status()
    return response.json()


def start_job(client: httpx.Client, worker_id: str, job_id: str) -> None:
    response = client.post(
        f"/workers/{worker_id}/jobs/{job_id}/start",
    )
    response.raise_for_status()


def renew_lease(
    client: httpx.Client,
    worker_id: str,
) -> tuple[bool, str | None]:
    """
    Returns (lease_still_held, job_status).

    lease_still_held is False if the lease is already gone
    (409): the caller must stop renewing and must not persist
    whatever the subprocess eventually returns, someone else
    may already own this job (ADR 0011).

    job_status is the assigned job's current status as of
    this renewal (ADR 0029), read from the same response
    every renewal already receives rather than a separate
    call. None if the lease was lost.
    """
    response = client.post(
        f"/workers/{worker_id}/lease/renew",
    )

    if response.status_code == 409:
        return False, None

    response.raise_for_status()

    body = response.json()
    running_job = body.get("running_job")
    job_status = running_job["status"] if running_job else None

    return True, job_status


def report_outcome(
    client: httpx.Client,
    worker_id: str,
    job_id: str,
    result: JobExecutionResult,
) -> None:
    """
    Report a job's real outcome: cancelled, completed, or
    failed (ADR 0029). cancelled is checked first, since a
    cancelled result is also not succeeded and would
    otherwise be misreported as a plain failure.
    """
    if result.cancelled:
        path = "cancel"
    elif result.succeeded:
        path = "complete"
    else:
        path = "fail"

    response = client.post(
        f"/workers/{worker_id}/jobs/{job_id}/{path}",
        json={"exit_code": result.exit_code},
    )

    if response.status_code == 409:
        print(
            f"Job {job_id}: outcome not recorded, lease or "
            f"ownership already lost. Dropping result."
        )
        return

    response.raise_for_status()


def run_job(
    client: httpx.Client,
    worker_id: str,
    job: dict,
) -> None:
    job_id = job["id"]
    command = job["command"]
    timeout = timedelta(
        seconds=job["execution_timeout_seconds"],
    )

    print(f"Starting job {job_id} (command={command})")
    start_job(client, worker_id, job_id)

    stop_renewing = threading.Event()
    cancel_event = threading.Event()
    lost_lease = threading.Event()

    def keep_lease_alive() -> None:
        while not stop_renewing.wait(RENEWAL_INTERVAL_SECONDS):
            try:
                lease_ok, job_status = renew_lease(
                    client,
                    worker_id,
                )
            except httpx.HTTPError as exc:
                print(
                    f"Lease renewal failed: {exc}. "
                    f"Treating lease as lost."
                )
                lost_lease.set()
                return

            if not lease_ok:
                lost_lease.set()
                return

            if (
                not cancel_event.is_set()
                and job_status == "CANCELLING"
            ):
                cancel_event.set()

    renewal_thread = threading.Thread(
        target=keep_lease_alive,
        daemon=True,
    )
    renewal_thread.start()

    job_execution_service = JobExecutionService()

    try:
        result = job_execution_service.execute(
            command=command,
            timeout=timeout,
            cancel_event=cancel_event,
        )
    finally:
        stop_renewing.set()
        renewal_thread.join()

    if lost_lease.is_set():
        print(
            f"Job {job_id}: lease lost during execution. "
            f"Result computed but not reported."
        )
        return

    print(
        f"Job {job_id} finished: "
        f"succeeded={result.succeeded} "
        f"cancelled={result.cancelled} "
        f"exit_code={result.exit_code}"
    )

    report_outcome(
        client,
        worker_id,
        job_id,
        result,
    )


def main() -> None:
    if len(sys.argv) != 2:
        print(
            "Usage: python scripts/run_agent.py <node-id>",
            file=sys.stderr,
        )
        raise SystemExit(1)

    node_id = sys.argv[1]

    api_key = os.getenv("AETHERGRID_API_KEY")

    if not api_key:
        print(
            "AETHERGRID_API_KEY environment variable is not set. "
            "Issue one with scripts/issue_api_key.py first.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    client = _client(api_key)

    worker_id = register_worker(client, node_id)

    # Heartbeating runs on its own background thread for the
    # agent's entire lifetime, independent of whether a job is
    # currently executing. Without this, a worker that picks up a
    # long-running job would only heartbeat once, before starting
    # it, and could exceed the 1-minute HEARTBEAT_TIMEOUT and be
    # marked OFFLINE by the cluster's dead-worker sweep mid-job,
    # even though the agent process is alive and working the
    # whole time.
    stop_heartbeating = threading.Event()

    def keep_heartbeating() -> None:
        # Both the worker and the node it belongs to need
        # independent, continuous heartbeats. Worker.is_alive()
        # and Node.is_alive() are separate clocks (same as
        # useWorkerHeartbeatKeeper.ts already documented for the
        # browser-tab stand-in this agent replaces); nothing else
        # heartbeats the node on an interval once this agent is
        # the thing driving the cluster, and a node the scheduler
        # considers dead will never have jobs scheduled onto it,
        # regardless of how alive its worker looks.
        while not stop_heartbeating.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                heartbeat_worker(client, worker_id)
                heartbeat_node(client, node_id)
            except httpx.HTTPError as exc:
                print(f"Heartbeat failed: {exc}")

    heartbeat_thread = threading.Thread(
        target=keep_heartbeating,
        daemon=True,
    )
    heartbeat_thread.start()

    # Send one heartbeat of each immediately, don't wait for the
    # first HEARTBEAT_INTERVAL_SECONDS tick.
    heartbeat_worker(client, worker_id)
    heartbeat_node(client, node_id)

    print(
        f"Agent running. Polling every {POLL_INTERVAL_SECONDS}s, "
        f"heartbeating every {HEARTBEAT_INTERVAL_SECONDS}s. "
        f"Ctrl+C to stop."
    )

    try:
        while True:
            worker = get_worker(client, worker_id)
            running_job = worker["running_job"]

            if running_job is not None:
                run_job(client, worker_id, running_job)
            else:
                time.sleep(POLL_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nAgent stopped.")
    finally:
        stop_heartbeating.set()
        heartbeat_thread.join()


if __name__ == "__main__":
    main()
