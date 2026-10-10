from __future__ import annotations

import pytest

from app.domain.entities.job import Job
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.enums.job_status import JobStatus
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.tenant_id import TenantId
from tests.support.jobs import make_job


def test_a_job_carries_the_tenant_it_is_built_with() -> None:
    tenant_id = TenantId.new()

    assert make_job(tenant_id=tenant_id).tenant_id == tenant_id


def test_make_job_defaults_to_the_default_tenant() -> None:
    assert make_job().tenant_id == DEFAULT_TENANT_ID


def test_a_job_cannot_be_built_without_a_tenant() -> None:
    with pytest.raises(TypeError):
        Job(
            id=JobId.new(),
            resources=ResourceRequirements(
                cpu_cores=1,
                memory_mib=512,
                vram_mib=0,
            ),
        )


def test_the_tenant_survives_every_transition_that_requeues_a_job() -> None:
    tenant_id = TenantId.new()
    job = make_job(tenant_id=tenant_id, max_retries=3)

    job.queue()
    job.assign_to(NodeId.new())
    job.unschedule()
    assert job.status is JobStatus.QUEUED
    assert job.tenant_id == tenant_id

    job.assign_to(NodeId.new())
    job.start()
    job.reclaim()
    assert job.status is JobStatus.QUEUED
    assert job.tenant_id == tenant_id

    job.assign_to(NodeId.new())
    job.start()
    job.fail(exit_code=1)
    job.retry()
    assert job.status is JobStatus.QUEUED
    assert job.tenant_id == tenant_id
