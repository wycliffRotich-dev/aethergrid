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

Failure handling: an unattended agent must survive a control
plane that is restarting, overloaded, or rate limiting it. Calls
that fail transiently (429, 5xx, transport errors) are retried
with capped exponential backoff and full jitter, honoring
Retry-After. Failures that retrying cannot fix (401, 404 on
registration, 422) stop the agent with a clear message.

Usage:
    export AETHERGRID_API_KEY="<key from scripts/issue_api_key.py>"
    python scripts/run_agent.py <node-id>

The node must already be registered (via the API or dashboard)
before starting an agent against it.
"""
from __future__ import annotations

import os
import random
import sys
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from functools import partial
from typing import TypeVar

import httpx

from app.application.services.job_execution_service import (
    JobExecutionResult,
    JobExecutionService,
)
from app.domain.entities.lease import DEFAULT_LEASE_DURATION

T = TypeVar("T")

POLL_INTERVAL_SECONDS = 5.0
HEARTBEAT_INTERVAL_SECONDS = 5.0
RENEWAL_INTERVAL_SECONDS = DEFAULT_LEASE_DURATION.total_seconds() / 3
API_BASE_URL = os.getenv(
    "AETHERGRID_API_URL",
    "http://localhost:8000",
)

# Retry policy for transient failures. The ceiling of each retry
# doubles from BACKOFF_BASE_SECONDS up to BACKOFF_CAP_SECONDS, and
# the actual delay is drawn uniformly from [0, ceiling] (full
# jitter) so a fleet that failed together does not retry together.
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 30.0
MAX_BACKOFF_EXPONENT = 10

# Steady-state intervals are spread by this fraction either side so
# agents started at the same instant drift apart instead of hitting
# the API in lockstep forever.
INTERVAL_JITTER_FRACTION = 0.2

# HTTP statuses meaning this agent's view of the world is stale
# (worker deleted, job or lease no longer ours). The correct
# response is to return to the poll loop, not to crash.
STALE_VIEW_STATUS_CODES = frozenset({404, 409})

# How long an agent keeps trusting a lease it cannot renew. The
# lease is at most one poll interval old when the agent first sees
# it, so trusting it for the full duration would outlast the real
# expiry. Measured from the last confirmed renewal on this
# agent's own monotonic clock, never from a server timestamp.
LEASE_AGE_MARGIN_SECONDS = POLL_INTERVAL_SECONDS
LEASE_TRUST_WINDOW_SECONDS = (
    DEFAULT_LEASE_DURATION.total_seconds() - LEASE_AGE_MARGIN_SECONDS
)

_JITTER_RNG = random.Random()


class AgentError(Exception):
    """Raised for agent-level failures that should stop the run."""


def _client(api_key: str) -> httpx.Client:
    return httpx.Client(
        base_url=API_BASE_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10.0,
    )


def is_transient(exc: httpx.HTTPError) -> bool:
    """
    True if retrying the same request can plausibly succeed:
    rate limiting, server-side failure, or the request never
    completing (connect errors, timeouts, dropped connections).
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or status_code >= 500

    return isinstance(exc, httpx.TransportError)


def is_stale_view(exc: httpx.HTTPError) -> bool:
    """
    True if the server is telling this agent that what it
    believes it owns (worker, job, lease) is no longer true.
    """
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in STALE_VIEW_STATUS_CODES
    )


def retry_after_seconds(exc: httpx.HTTPError) -> float | None:
    """
    The server's Retry-After hint in seconds, if the failure
    carried a well-formed one. The API sends integer seconds.
    """
    if not isinstance(exc, httpx.HTTPStatusError):
        return None

    raw = exc.response.headers.get("Retry-After")

    if raw is None:
        return None

    try:
        value = float(raw)
    except ValueError:
        return None

    return value if value >= 0.0 else None


def backoff_delay_seconds(
    attempt: int,
    retry_after: float | None = None,
    rng: random.Random = _JITTER_RNG,
) -> float:
    """
    Delay before retry number `attempt` (0-based): full jitter
    under an exponentially growing, capped ceiling, never less
    than the server's Retry-After when one was given.
    """
    exponent = min(attempt, MAX_BACKOFF_EXPONENT)
    ceiling = min(
        BACKOFF_CAP_SECONDS,
        BACKOFF_BASE_SECONDS * (2**exponent),
    )
    jittered = rng.uniform(0.0, ceiling)

    return max(jittered, retry_after or 0.0)


def jittered_interval_seconds(
    base: float,
    rng: random.Random = _JITTER_RNG,
) -> float:
    spread = base * INTERVAL_JITTER_FRACTION

    return rng.uniform(base - spread, base + spread)


def describe_http_error(exc: httpx.HTTPStatusError) -> str:
    response = exc.response

    return (
        f"HTTP {response.status_code} from "
        f"{exc.request.method} {exc.request.url.path}: "
        f"{response.text[:200]}"
    )


def call_with_retry(
    operation: Callable[[], T],
    *,
    description: str,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random = _JITTER_RNG,
) -> T:
    """
    Run `operation`, retrying without limit while it fails
    transiently. Non-transient failures propagate immediately.

    Unbounded on purpose: an unattended agent must outlast a
    control plane outage. The operator stops it with Ctrl+C.
    """
    attempt = 0

    while True:
        try:
            return operation()
        except httpx.HTTPError as exc:
            if not is_transient(exc):
                raise

            delay = backoff_delay_seconds(
                attempt,
                retry_after_seconds(exc),
                rng,
            )
            print(
                f"{description} failed: {exc}. "
                f"Retrying in {delay:.1f}s."
            )
            sleep(delay)
            attempt += 1


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


def register_with_retry(
    client: httpx.Client,
    node_id: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random = _JITTER_RNG,
) -> str:
    """
    Register against the node, retrying transient failures.

    Registration is idempotent per node (ADR 0030), so a retry
    after a lost response converges on the same worker. A
    rejection that retrying cannot change (unknown node, bad
    credentials) raises AgentError.
    """
    try:
        return call_with_retry(
            lambda: register_worker(client, node_id),
            description="Registration",
            sleep=sleep,
            rng=rng,
        )
    except httpx.HTTPStatusError as exc:
        raise AgentError(
            f"registration rejected: {describe_http_error(exc)}"
        ) from exc


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
    lease_id: str,
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
        json={"lease_id": lease_id},
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
    lease_id: str,
    result: JobExecutionResult,
) -> None:
    """
    Report a job's real outcome: cancelled, completed, or
    failed (ADR 0029). cancelled is checked first, since a
    cancelled result is also not succeeded and would
    otherwise be misreported as a plain failure.

    lease_id (ADR 0036) is the lease this agent believed it
    held when it started executing this job, captured from
    the poll response before start_job() was ever called, not
    re-fetched here. The server fences this report against
    whatever lease is actually current for this worker;
    sending a freshly re-fetched value instead would defeat
    the fencing entirely, since it could never disagree with
    itself.

    Transient failures are retried. That is safe because the
    report is fenced by lease identity: if an earlier attempt
    was applied but its response was lost, the retry is
    answered with 409 and dropped below, which is correct.
    """
    if result.cancelled:
        path = "cancel"
    elif result.succeeded:
        path = "complete"
    else:
        path = "fail"

    def post_outcome() -> httpx.Response:
        response = client.post(
            f"/workers/{worker_id}/jobs/{job_id}/{path}",
            json={
                "exit_code": result.exit_code,
                "lease_id": lease_id,
            },
        )

        if response.status_code != 409:
            response.raise_for_status()

        return response

    response = call_with_retry(
        post_outcome,
        description=f"Job {job_id} outcome report",
    )

    if response.status_code == 409:
        print(
            f"Job {job_id}: outcome not recorded, lease or "
            f"ownership already lost. Dropping result."
        )


def run_job(
    client: httpx.Client,
    worker_id: str,
    job: dict,
) -> None:
    job_id = job["id"]
    command = job["command"]
    lease_id = job["lease_id"]
    timeout = timedelta(
        seconds=job["execution_timeout_seconds"],
    )

    print(f"Starting job {job_id} (command={command})")
    start_job(client, worker_id, job_id)

    stop_renewing = threading.Event()
    cancel_event = threading.Event()
    lost_lease = threading.Event()

    def keep_lease_alive() -> None:
        last_confirmed_at = time.monotonic()
        wait = RENEWAL_INTERVAL_SECONDS
        attempt = 0

        while not stop_renewing.wait(wait):
            attempted_at = time.monotonic()

            try:
                lease_ok, job_status = renew_lease(
                    client,
                    worker_id,
                    lease_id,
                )
            except httpx.HTTPError as exc:
                now = time.monotonic()
                trust_deadline = (
                    last_confirmed_at + LEASE_TRUST_WINDOW_SECONDS
                )

                if not is_transient(exc) or now >= trust_deadline:
                    print(
                        f"Lease renewal failed: {exc}. "
                        f"Treating lease as lost."
                    )
                    lost_lease.set()
                    return

                wait = min(
                    backoff_delay_seconds(
                        attempt,
                        retry_after_seconds(exc),
                    ),
                    trust_deadline - now,
                )
                attempt += 1
                print(
                    f"Lease renewal failed transiently: {exc}. "
                    f"Retrying in {wait:.1f}s."
                )
                continue

            attempt = 0
            wait = RENEWAL_INTERVAL_SECONDS

            if not lease_ok:
                lost_lease.set()
                return

            last_confirmed_at = attempted_at

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
        lease_id,
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

    try:
        worker_id = register_with_retry(client, node_id)
    except KeyboardInterrupt:
        print("\nAgent stopped.")
        return
    except AgentError as exc:
        print(f"Agent cannot start: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

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
        #
        # worker_id is read from main()'s scope on every
        # iteration, so a re-registration that reassigns it is
        # picked up here without any extra synchronization.
        while not stop_heartbeating.wait(
            jittered_interval_seconds(HEARTBEAT_INTERVAL_SECONDS),
        ):
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

    exit_code = 0

    try:
        # Send one heartbeat of each immediately, don't wait for
        # the first HEARTBEAT_INTERVAL_SECONDS tick.
        call_with_retry(
            lambda: heartbeat_worker(client, worker_id),
            description="Initial worker heartbeat",
        )
        call_with_retry(
            lambda: heartbeat_node(client, node_id),
            description="Initial node heartbeat",
        )

        print(
            f"Agent running. Polling every "
            f"{POLL_INTERVAL_SECONDS}s, heartbeating every "
            f"{HEARTBEAT_INTERVAL_SECONDS}s. Ctrl+C to stop."
        )

        while True:
            try:
                worker = call_with_retry(
                    partial(get_worker, client, worker_id),
                    description="Poll",
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise

                # The worker row is gone (for example the node
                # was removed and its workers cascaded, ADR
                # 0030). Registration is idempotent per node, so
                # registering again is always safe.
                print(
                    "Worker no longer exists on the server. "
                    "Re-registering."
                )
                worker_id = register_with_retry(client, node_id)
                continue

            running_job = worker["running_job"]

            if running_job is None:
                time.sleep(
                    jittered_interval_seconds(POLL_INTERVAL_SECONDS),
                )
                continue

            try:
                run_job(client, worker_id, running_job)
            except httpx.HTTPError as exc:
                if not (is_transient(exc) or is_stale_view(exc)):
                    raise

                # Back to the poll loop: it re-reads the server's
                # current view, which is the only authority on
                # what this worker holds. The sleep prevents a
                # hot loop against a struggling API.
                print(
                    f"Job handoff interrupted: {exc}. "
                    f"Returning to poll loop."
                )
                time.sleep(
                    jittered_interval_seconds(POLL_INTERVAL_SECONDS),
                )

    except KeyboardInterrupt:
        print("\nAgent stopped.")
    except AgentError as exc:
        print(f"Agent stopping: {exc}", file=sys.stderr)
        exit_code = 1
    except httpx.HTTPStatusError as exc:
        print(
            f"Agent stopping: {describe_http_error(exc)}",
            file=sys.stderr,
        )
        exit_code = 1
    finally:
        stop_heartbeating.set()
        heartbeat_thread.join()

    if exit_code != 0:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
