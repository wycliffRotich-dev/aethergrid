"""
ADR 0102, decisions 5 and 9, and ADR 0094, decision 3. The public response
models.

Each model has the fields of its port record, in the same order, and a node
adds the allocation of each resource, which is capacity minus available. No
name, title or description says usage or utilization. A node whose available
amount is above its capacity is refused, so a page never prints a negative
allocation. Every model is defined in the public package, and none builds on
app.presentation.schemas.
"""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app.application.public_read_port import (
    PublicEventRecord,
    PublicJobRecord,
    PublicLeaseRecord,
    PublicNodeRecord,
    PublicWorkerRecord,
)
from app.presentation.public.responses import (
    PublicEventResponse,
    PublicJobResponse,
    PublicLeaseResponse,
    PublicNodeResponse,
    PublicWorkerResponse,
)

MODULE = "app.presentation.public.responses"
SCHEMAS_PACKAGE = "app.presentation.schemas"
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
LATER = datetime(2026, 1, 2, 3, 9, 5, tzinfo=UTC)
ALLOCATED = ["allocated_cpu_cores", "allocated_memory_mib", "allocated_vram_mib"]
USE_WORDS = {"usage", "used", "utilization", "utilisation", "util", "load"}


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


PENDING = {
    "status": "PENDING",
    "assigned_node_id": None,
    "started_at": None,
    "completed_at": None,
    "execution_timeout_seconds": None,
}

PAIRS = [
    pytest.param(node(), PublicNodeResponse, ALLOCATED, id="node"),
    pytest.param(node(draining=False), PublicNodeResponse, ALLOCATED, id="node-idle"),
    pytest.param(job(), PublicJobResponse, [], id="job-running"),
    pytest.param(job(**PENDING), PublicJobResponse, [], id="job-pending"),
    pytest.param(worker(), PublicWorkerResponse, [], id="worker-busy"),
    pytest.param(
        worker(status="IDLE", running_job_id=None),
        PublicWorkerResponse,
        [],
        id="worker-idle",
    ),
    pytest.param(lease(), PublicLeaseResponse, [], id="lease"),
    pytest.param(event(), PublicEventResponse, [], id="event"),
]

RESPONSES = [
    pytest.param(response, id=response.__name__)
    for response in (
        PublicNodeResponse,
        PublicJobResponse,
        PublicWorkerResponse,
        PublicLeaseResponse,
        PublicEventResponse,
    )
]

ALLOCATIONS = [
    pytest.param((8, 16384, 2048), (3, 5000, 2000), (5, 11384, 48), id="partly-allocated"),
    pytest.param((16, 1000, 500), (16, 1, 0), (0, 999, 500), id="cpu-free-rest-taken"),
    pytest.param((4, 2048, 0), (1, 48, 0), (3, 2000, 0), id="a-node-without-vram"),
    pytest.param((4, 2048, 512), (4, 2048, 512), (0, 0, 0), id="nothing-allocated"),
]


def _words(value: Any) -> set[str]:
    return set(re.findall(r"[a-z]+", json.dumps(value).lower()))


def _use_words(value: Any) -> set[str]:
    return _words(value) & USE_WORDS


def _private_bases(cls: type) -> list[str]:
    return [
        base.__module__
        for base in cls.__mro__
        if base.__module__.startswith(SCHEMAS_PACKAGE)
    ]


@pytest.mark.parametrize(("record", "response", "derived"), PAIRS)
def test_a_response_has_the_fields_of_its_record_and_only_the_named_extras(
    record: Any, response: type[BaseModel], derived: list[str]
) -> None:
    names = [field.name for field in dataclasses.fields(record)]

    assert list(response.model_fields) == names + derived


@pytest.mark.parametrize(("record", "response", "derived"), PAIRS)
def test_every_field_of_the_record_is_copied_unchanged(
    record: Any, response: Any, derived: list[str]
) -> None:
    built = response.from_record(record)

    assert type(built) is response

    for field in dataclasses.fields(record):
        assert getattr(built, field.name) == getattr(record, field.name), field.name


@pytest.mark.parametrize(("capacity", "available", "expected"), ALLOCATIONS)
def test_allocation_is_capacity_minus_available(
    capacity: tuple[int, int, int],
    available: tuple[int, int, int],
    expected: tuple[int, int, int],
) -> None:
    built = PublicNodeResponse.from_record(
        node(
            capacity_cpu_cores=capacity[0],
            capacity_memory_mib=capacity[1],
            capacity_vram_mib=capacity[2],
            available_cpu_cores=available[0],
            available_memory_mib=available[1],
            available_vram_mib=available[2],
        )
    )

    assert (
        built.allocated_cpu_cores,
        built.allocated_memory_mib,
        built.allocated_vram_mib,
    ) == expected


@pytest.mark.parametrize("resource", ["cpu_cores", "memory_mib", "vram_mib"])
def test_an_available_amount_above_capacity_is_refused(resource: str) -> None:
    capacity = getattr(node(), f"capacity_{resource}")
    row = node(**{f"available_{resource}": capacity + 1})

    with pytest.raises(ValidationError):
        PublicNodeResponse.from_record(row)


@pytest.mark.parametrize(("record", "response", "derived"), PAIRS)
def test_a_response_is_frozen_and_refuses_an_extra_field(
    record: Any, response: Any, derived: list[str]
) -> None:
    built = response.from_record(record)
    first = next(iter(response.model_fields))

    with pytest.raises(ValidationError):
        setattr(built, first, getattr(built, first))

    with pytest.raises(ValidationError):
        response(**{**built.model_dump(), "tenant_id": "t"})


@pytest.mark.parametrize("response", RESPONSES)
def test_no_name_title_or_description_says_usage(response: type[BaseModel]) -> None:
    assert _use_words(response.model_json_schema()) == set()


def test_the_word_check_flags_each_use_word_and_keeps_word_boundaries() -> None:
    flagged = _use_words(
        {"cpu_usage": 1, "title": "Memory Used", "gpu": "Load", "x": "Utilization"}
    )

    assert flagged == {"usage", "used", "load", "utilization"}
    assert _use_words({"payload": 1, "downloaded": 2, "allocated_cpu_cores": 3}) == set()


@pytest.mark.parametrize("response", RESPONSES)
def test_a_response_is_defined_in_the_public_package_on_no_private_base(
    response: type[BaseModel],
) -> None:
    assert response.__module__ == MODULE
    assert _private_bases(response) == []


def test_the_base_check_flags_a_private_base() -> None:
    private = type("Private", (BaseModel,), {"__module__": f"{SCHEMAS_PACKAGE}.fake"})
    child = type("Child", (private,), {})

    assert _private_bases(child) == [f"{SCHEMAS_PACKAGE}.fake"]
    assert _private_bases(PublicNodeResponse) == []
