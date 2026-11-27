"""
The response models of the public app (ADR 0102, decisions 5 and 9, and
ADR 0109, decision 7).

Each model has the fields of its port record, in the same order, so a field
is public only when it is written here on purpose (ADR 0094, decision 3).
A node adds the allocation of each resource, which is capacity minus
available. Nothing here says usage or utilization. An available amount above
the capacity is refused, so a page never prints a negative allocation.
Nothing is imported from app.presentation.schemas.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.application.public_read_port import (
    PublicEventRecord,
    PublicJobRecord,
    PublicLeaseReclaimRecord,
    PublicLeaseRecord,
    PublicLeaseRefusalRecord,
    PublicNodeRecord,
    PublicWorkerRecord,
)


class _PublicResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PublicNodeResponse(_PublicResponse):
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
    allocated_cpu_cores: int = Field(ge=0)
    allocated_memory_mib: int = Field(ge=0)
    allocated_vram_mib: int = Field(ge=0)

    @classmethod
    def from_record(cls, record: PublicNodeRecord) -> PublicNodeResponse:
        return cls(
            id=record.id,
            name=record.name,
            capacity_cpu_cores=record.capacity_cpu_cores,
            capacity_memory_mib=record.capacity_memory_mib,
            capacity_vram_mib=record.capacity_vram_mib,
            available_cpu_cores=record.available_cpu_cores,
            available_memory_mib=record.available_memory_mib,
            available_vram_mib=record.available_vram_mib,
            last_seen_at=record.last_seen_at,
            draining=record.draining,
            allocated_cpu_cores=record.capacity_cpu_cores - record.available_cpu_cores,
            allocated_memory_mib=record.capacity_memory_mib - record.available_memory_mib,
            allocated_vram_mib=record.capacity_vram_mib - record.available_vram_mib,
        )


class PublicJobResponse(_PublicResponse):
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

    @classmethod
    def from_record(cls, record: PublicJobRecord) -> PublicJobResponse:
        return cls(
            id=record.id,
            cpu_cores=record.cpu_cores,
            memory_mib=record.memory_mib,
            vram_mib=record.vram_mib,
            priority=record.priority,
            max_retries=record.max_retries,
            retry_count=record.retry_count,
            status=record.status,
            assigned_node_id=record.assigned_node_id,
            submitted_at=record.submitted_at,
            started_at=record.started_at,
            completed_at=record.completed_at,
            execution_timeout_seconds=record.execution_timeout_seconds,
        )


class PublicWorkerResponse(_PublicResponse):
    id: UUID
    node_id: UUID
    status: str
    running_job_id: UUID | None
    last_seen_at: datetime

    @classmethod
    def from_record(cls, record: PublicWorkerRecord) -> PublicWorkerResponse:
        return cls(
            id=record.id,
            node_id=record.node_id,
            status=record.status,
            running_job_id=record.running_job_id,
            last_seen_at=record.last_seen_at,
        )


class PublicLeaseResponse(_PublicResponse):
    id: UUID
    worker_id: UUID
    job_id: UUID
    acquired_at: datetime
    expires_at: datetime

    @classmethod
    def from_record(cls, record: PublicLeaseRecord) -> PublicLeaseResponse:
        return cls(
            id=record.id,
            worker_id=record.worker_id,
            job_id=record.job_id,
            acquired_at=record.acquired_at,
            expires_at=record.expires_at,
        )


class PublicEventResponse(_PublicResponse):
    id: UUID
    aggregate_id: str
    aggregate_type: str
    event_type: str
    occurred_at: datetime

    @classmethod
    def from_record(cls, record: PublicEventRecord) -> PublicEventResponse:
        return cls(
            id=record.id,
            aggregate_id=record.aggregate_id,
            aggregate_type=record.aggregate_type,
            event_type=record.event_type,
            occurred_at=record.occurred_at,
        )


class PublicLeaseReclaimResponse(_PublicResponse):
    id: UUID
    lease_id: UUID
    worker_id: UUID
    job_id: UUID
    lease_acquired_at: datetime
    lease_expires_at: datetime
    reclaimed_at: datetime
    recovered_by: str

    @classmethod
    def from_record(
        cls, record: PublicLeaseReclaimRecord
    ) -> PublicLeaseReclaimResponse:
        return cls(
            id=record.id,
            lease_id=record.lease_id,
            worker_id=record.worker_id,
            job_id=record.job_id,
            lease_acquired_at=record.lease_acquired_at,
            lease_expires_at=record.lease_expires_at,
            reclaimed_at=record.reclaimed_at,
            recovered_by=record.recovered_by,
        )


class PublicLeaseRefusalResponse(_PublicResponse):
    id: UUID
    lease_id: UUID
    worker_id: UUID
    job_id: UUID
    operation: str
    reason: str
    refused_at: datetime

    @classmethod
    def from_record(
        cls, record: PublicLeaseRefusalRecord
    ) -> PublicLeaseRefusalResponse:
        return cls(
            id=record.id,
            lease_id=record.lease_id,
            worker_id=record.worker_id,
            job_id=record.job_id,
            operation=record.operation,
            reason=record.reason,
            refused_at=record.refused_at,
        )
