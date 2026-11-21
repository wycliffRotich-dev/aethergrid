"""
Shared helpers for tests of the public app (ADR 0102).

A fake reader stands behind the port, records what it was asked and can be
told to fail. The settings are the ones the tests build the app from, and
there is one factory for each kind of record.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.application.public_read_port import (
    PublicEventRecord,
    PublicJobRecord,
    PublicLeaseRecord,
    PublicNodeRecord,
    PublicWorkerRecord,
)
from app.presentation.public.settings import PublicSettings

ORIGIN = "https://demo.example.org"
URL = "postgresql://aethergrid_public_app@db.internal:5432/aethergrid"
PASSWORD_FILE = "/run/secrets/public_db_password"
# Every path the public app serves. A route is added here on purpose, in
# the same change that adds the route.
PUBLIC_PATHS = {
    "/healthz",
    "/public/events",
    "/public/jobs",
    "/public/leases",
    "/public/nodes",
    "/public/workers",
}
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
LATER = datetime(2026, 1, 2, 3, 9, 5, tzinfo=UTC)


def make_settings(hops: int = 0) -> PublicSettings:
    return PublicSettings.from_environment(
        {
            "AETHERGRID_PUBLIC_ALLOWED_ORIGIN": ORIGIN,
            "AETHERGRID_PUBLIC_DATABASE_URL": URL,
            "AETHERGRID_PUBLIC_DATABASE_PASSWORD_FILE": PASSWORD_FILE,
            "AETHERGRID_PUBLIC_TRUSTED_PROXY_HOPS": str(hops),
        }
    )


class FakePublicReader:
    """Answers from lists, remembers each call, and raises when told to."""

    def __init__(
        self,
        *,
        nodes: Sequence[PublicNodeRecord] = (),
        jobs: Sequence[PublicJobRecord] = (),
        workers: Sequence[PublicWorkerRecord] = (),
        leases: Sequence[PublicLeaseRecord] = (),
        events: Sequence[PublicEventRecord] = (),
        error: BaseException | None = None,
    ) -> None:
        self.nodes = nodes
        self.jobs = jobs
        self.workers = workers
        self.leases = leases
        self.events = events
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def _answer(self, method: str, limit: int, rows: Sequence[Any]) -> list[Any]:
        self.calls.append((method, limit))

        if self.error is not None:
            raise self.error

        return list(rows)

    def list_nodes(self, limit: int) -> Sequence[PublicNodeRecord]:
        return self._answer("list_nodes", limit, self.nodes)

    def list_jobs(self, limit: int) -> Sequence[PublicJobRecord]:
        return self._answer("list_jobs", limit, self.jobs)

    def list_workers(self, limit: int) -> Sequence[PublicWorkerRecord]:
        return self._answer("list_workers", limit, self.workers)

    def list_leases(self, limit: int) -> Sequence[PublicLeaseRecord]:
        return self._answer("list_leases", limit, self.leases)

    def list_events(self, limit: int) -> Sequence[PublicEventRecord]:
        return self._answer("list_events", limit, self.events)


def node(**changes: Any) -> PublicNodeRecord:
    values: dict[str, Any] = {
        "id": uuid4(),
        "name": "node-a",
        "capacity_cpu_cores": 8,
        "capacity_memory_mib": 16384,
        "capacity_vram_mib": 2048,
        "available_cpu_cores": 3,
        "available_memory_mib": 5000,
        "available_vram_mib": 2000,
        "last_seen_at": NOW,
        "draining": True,
    }
    return PublicNodeRecord(**{**values, **changes})


def job(**changes: Any) -> PublicJobRecord:
    values: dict[str, Any] = {
        "id": uuid4(),
        "cpu_cores": 2,
        "memory_mib": 512,
        "vram_mib": 128,
        "priority": 7,
        "max_retries": 4,
        "retry_count": 1,
        "status": "RUNNING",
        "assigned_node_id": uuid4(),
        "submitted_at": NOW,
        "started_at": LATER,
        "completed_at": None,
        "execution_timeout_seconds": 90.5,
    }
    return PublicJobRecord(**{**values, **changes})


def worker(**changes: Any) -> PublicWorkerRecord:
    values: dict[str, Any] = {
        "id": uuid4(),
        "node_id": uuid4(),
        "status": "BUSY",
        "running_job_id": uuid4(),
        "last_seen_at": NOW,
    }
    return PublicWorkerRecord(**{**values, **changes})


def lease() -> PublicLeaseRecord:
    return PublicLeaseRecord(
        id=uuid4(),
        worker_id=uuid4(),
        job_id=uuid4(),
        acquired_at=NOW,
        expires_at=LATER,
    )


def event() -> PublicEventRecord:
    return PublicEventRecord(
        id=uuid4(),
        aggregate_id="job-1",
        aggregate_type="job",
        event_type="JOB_STARTED",
        occurred_at=LATER,
    )
