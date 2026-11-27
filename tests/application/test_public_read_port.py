"""
ADR 0102, decision 1. The public read port: a read-only protocol with one
method per public view, and one frozen record per view with exactly the
view's columns (ADR 0098). No method takes a tenant, and nothing can write.
"""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, get_type_hints
from uuid import UUID

import pytest

from app.application.public_read_port import (
    PublicEventRecord,
    PublicJobRecord,
    PublicLeaseReclaimRecord,
    PublicLeaseRecord,
    PublicLeaseRefusalRecord,
    PublicNodeRecord,
    PublicReadPort,
    PublicWorkerRecord,
)

# The columns of the seven views of migrations 0007 and 0010, in order, with the type
# each one has in the base table. Nullable columns are optional.
RECORDS: dict[type, dict[str, object]] = {
    PublicNodeRecord: {
        "id": UUID,
        "name": str,
        "capacity_cpu_cores": int,
        "capacity_memory_mib": int,
        "capacity_vram_mib": int,
        "available_cpu_cores": int,
        "available_memory_mib": int,
        "available_vram_mib": int,
        "last_seen_at": datetime,
        "draining": bool,
    },
    PublicJobRecord: {
        "id": UUID,
        "cpu_cores": int,
        "memory_mib": int,
        "vram_mib": int,
        "priority": int,
        "max_retries": int,
        "retry_count": int,
        "status": str,
        "assigned_node_id": UUID | None,
        "submitted_at": datetime,
        "started_at": datetime | None,
        "completed_at": datetime | None,
        "execution_timeout_seconds": float | None,
    },
    PublicWorkerRecord: {
        "id": UUID,
        "node_id": UUID,
        "status": str,
        "running_job_id": UUID | None,
        "last_seen_at": datetime,
    },
    PublicLeaseRecord: {
        "id": UUID,
        "worker_id": UUID,
        "job_id": UUID,
        "acquired_at": datetime,
        "expires_at": datetime,
    },
    PublicEventRecord: {
        "id": UUID,
        "aggregate_id": str,
        "aggregate_type": str,
        "event_type": str,
        "occurred_at": datetime,
    },
    PublicLeaseReclaimRecord: {
        "id": UUID,
        "lease_id": UUID,
        "worker_id": UUID,
        "job_id": UUID,
        "lease_acquired_at": datetime,
        "lease_expires_at": datetime,
        "reclaimed_at": datetime,
        "recovered_by": str,
    },
    PublicLeaseRefusalRecord: {
        "id": UUID,
        "lease_id": UUID,
        "worker_id": UUID,
        "job_id": UUID,
        "operation": str,
        "reason": str,
        "refused_at": datetime,
    },
}

METHODS: dict[str, type] = {
    "list_nodes": PublicNodeRecord,
    "list_jobs": PublicJobRecord,
    "list_workers": PublicWorkerRecord,
    "list_leases": PublicLeaseRecord,
    "list_events": PublicEventRecord,
    "list_lease_reclaims": PublicLeaseReclaimRecord,
    "list_lease_refusals": PublicLeaseRefusalRecord,
}

PRIVATE_COLUMNS = {
    "tenant_id",
    "tenant",
    "command",
    "constraints",
    "labels",
    "exit_code",
    "cancellation_requested_at",
    "managed_by",
    "payload",
}


def public_methods() -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(PublicReadPort)
        if callable(member) and not name.startswith("_")
    }


@pytest.mark.parametrize("record", list(RECORDS))
class TestRecords:
    def test_the_fields_are_exactly_the_columns_of_the_view_in_order(
        self, record: type
    ) -> None:
        names = [field.name for field in dataclasses.fields(record)]

        assert names == list(RECORDS[record])

    def test_each_field_has_the_type_of_its_column(self, record: type) -> None:
        hints = get_type_hints(record)

        assert {name: hints[name] for name in RECORDS[record]} == RECORDS[record]

    def test_the_record_is_frozen(self, record: type) -> None:
        assert dataclasses.is_dataclass(record)
        assert record.__dataclass_params__.frozen  # type: ignore[attr-defined]

    def test_the_record_uses_slots(self, record: type) -> None:
        assert hasattr(record, "__slots__")

    def test_no_field_is_a_private_column(self, record: type) -> None:
        names = {field.name for field in dataclasses.fields(record)}

        assert names.isdisjoint(PRIVATE_COLUMNS)

    def test_no_field_says_usage_or_utilization(self, record: type) -> None:
        for field in dataclasses.fields(record):
            assert "usage" not in field.name
            assert "utilization" not in field.name

    def test_a_field_cannot_be_assigned_after_construction(
        self, record: type
    ) -> None:
        names = [field.name for field in dataclasses.fields(record)]
        values: dict[str, object] = {}

        for name, annotation in RECORDS[record].items():
            if annotation is UUID or annotation == UUID | None:
                values[name] = UUID(int=1)
            elif annotation is datetime or annotation == datetime | None:
                values[name] = datetime(2026, 1, 1)
            elif annotation is int:
                values[name] = 1
            elif annotation is bool:
                values[name] = False
            elif annotation is str:
                values[name] = "x"
            else:
                values[name] = 1.0

        instance = record(**values)

        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(instance, names[0], values[names[0]])


class TestPort:
    def test_it_is_a_protocol(self) -> None:
        assert Protocol in PublicReadPort.__mro__

    def test_it_has_one_method_per_view_and_nothing_else(self) -> None:
        assert public_methods() == set(METHODS)

    @pytest.mark.parametrize("method", list(METHODS))
    def test_a_method_takes_a_limit_and_nothing_else(self, method: str) -> None:
        signature = inspect.signature(getattr(PublicReadPort, method))

        assert list(signature.parameters) == ["self", "limit"]

    @pytest.mark.parametrize("method", list(METHODS))
    def test_the_limit_is_an_integer(self, method: str) -> None:
        hints = get_type_hints(getattr(PublicReadPort, method))

        assert hints["limit"] is int

    @pytest.mark.parametrize("method", list(METHODS))
    def test_a_method_returns_a_sequence_of_its_views_record(
        self, method: str
    ) -> None:
        hints = get_type_hints(getattr(PublicReadPort, method))

        assert hints["return"] == Sequence[METHODS[method]]  # type: ignore[valid-type]

    def test_no_method_takes_a_tenant(self) -> None:
        for method in METHODS:
            parameters = inspect.signature(getattr(PublicReadPort, method)).parameters

            assert "tenant" not in parameters
            assert "tenant_id" not in parameters

    def test_no_method_can_write(self) -> None:
        verbs = ("save", "create", "update", "delete", "insert", "set", "add")

        for name in public_methods():
            assert not name.startswith(verbs)
