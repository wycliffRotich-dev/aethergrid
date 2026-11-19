"""
The read port of the public demo (ADR 0102, decision 1).

A read-only protocol with one method per public view, and one frozen record
per view with exactly the columns of that view (ADR 0098, migration 0007).
No method takes a tenant: the tenant lives in the database and a caller can
never choose it. Nothing here writes.

Each method takes a limit. Clamping it to a fixed maximum and giving every
read a fixed order, events newest first, is the job of the reader that
implements this port, and tests there hold it to both.

The records use plain types. The domain gains nothing from the public app
(ADR 0094), so a status is the text the view holds, not a domain enum.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PublicNodeRecord:
    id: UUID
    name: str
    capacity_cpu_cores: int
    capacity_memory_mib: int
    capacity_vram_mib: int
    available_cpu_cores: int
    available_memory_mib: int
    available_vram_mib: int
    last_seen_at: datetime
    draining: bool


@dataclass(frozen=True, slots=True)
class PublicJobRecord:
    id: UUID
    cpu_cores: int
    memory_mib: int
    vram_mib: int
    priority: int
    max_retries: int
    retry_count: int
    status: str
    assigned_node_id: UUID | None
    submitted_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    execution_timeout_seconds: float | None


@dataclass(frozen=True, slots=True)
class PublicWorkerRecord:
    id: UUID
    node_id: UUID
    status: str
    running_job_id: UUID | None
    last_seen_at: datetime


@dataclass(frozen=True, slots=True)
class PublicLeaseRecord:
    id: UUID
    worker_id: UUID
    job_id: UUID
    acquired_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PublicEventRecord:
    id: UUID
    aggregate_id: str
    aggregate_type: str
    event_type: str
    occurred_at: datetime


class PublicReadPort(Protocol):
    def list_nodes(self, limit: int) -> Sequence[PublicNodeRecord]: ...

    def list_jobs(self, limit: int) -> Sequence[PublicJobRecord]: ...

    def list_workers(self, limit: int) -> Sequence[PublicWorkerRecord]: ...

    def list_leases(self, limit: int) -> Sequence[PublicLeaseRecord]: ...

    def list_events(self, limit: int) -> Sequence[PublicEventRecord]: ...
