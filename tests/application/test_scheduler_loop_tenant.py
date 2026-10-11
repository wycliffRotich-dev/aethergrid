from __future__ import annotations

from app.application.services.scheduler_loop_service import (
    SchedulerLoopService,
)
from app.domain.enums.job_status import JobStatus
from app.domain.services.scheduler import Scheduler
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node


def _loop(jobs, nodes):
    job_repository = InMemoryJobRepository(jobs)
    node_repository = InMemoryNodeRepository(nodes)
    loop = SchedulerLoopService(
        job_repository=job_repository,
        node_repository=node_repository,
        scheduler=Scheduler(),
    )
    return loop, job_repository, node_repository


def _queued(tenant_id):
    job = make_job(tenant_id=tenant_id)
    job.queue()
    return job


def test_a_job_is_not_scheduled_onto_another_tenants_node() -> None:
    tenant_a = TenantId.new()
    tenant_b = TenantId.new()
    job = _queued(tenant_a)
    foreign_node = make_node(tenant_id=tenant_b)
    full_capacity = foreign_node.available
    assert foreign_node.can_host(job.resources)
    loop, job_repository, node_repository = _loop([job], [foreign_node])

    loop.execute()

    stored = job_repository.get_by_id(job.id, tenant_a)
    assert stored is not None
    assert stored.status is JobStatus.QUEUED
    assert stored.assigned_node_id is None
    untouched = node_repository.get_by_id(foreign_node.id, tenant_b)
    assert untouched is not None
    assert untouched.available == full_capacity


def test_the_same_job_is_scheduled_when_its_own_tenant_has_a_node() -> None:
    tenant_a = TenantId.new()
    tenant_b = TenantId.new()
    job = _queued(tenant_a)
    own_node = make_node(tenant_id=tenant_a)
    foreign_node = make_node(tenant_id=tenant_b)
    loop, job_repository, _ = _loop([job], [foreign_node, own_node])

    loop.execute()

    stored = job_repository.get_by_id(job.id, tenant_a)
    assert stored is not None
    assert stored.status is JobStatus.SCHEDULED
    assert stored.assigned_node_id == own_node.id


def test_each_tenants_jobs_go_to_their_own_tenants_nodes() -> None:
    tenant_a = TenantId.new()
    tenant_b = TenantId.new()
    job_a = _queued(tenant_a)
    job_b = _queued(tenant_b)
    node_a = make_node(tenant_id=tenant_a)
    node_b = make_node(tenant_id=tenant_b)
    loop, job_repository, _ = _loop([job_a, job_b], [node_a, node_b])

    loop.execute()

    stored_a = job_repository.get_by_id(job_a.id, tenant_a)
    stored_b = job_repository.get_by_id(job_b.id, tenant_b)
    assert stored_a is not None and stored_b is not None
    assert stored_a.assigned_node_id == node_a.id
    assert stored_b.assigned_node_id == node_b.id
