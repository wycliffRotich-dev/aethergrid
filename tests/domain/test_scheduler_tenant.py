from __future__ import annotations

from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.services.scheduler import Scheduler
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.tenant_id import TenantId
from tests.support.jobs import make_job
from tests.support.nodes import make_node


def test_a_job_is_never_placed_on_another_tenants_node() -> None:
    job = make_job()
    foreign_node = make_node(tenant_id=TenantId.new())

    assert foreign_node.can_host(job.resources)
    assert Scheduler().select_node(job, [foreign_node]) is None


def test_a_job_prefers_its_own_tenant_even_when_another_fits_tighter() -> None:
    tenant_a = TenantId.new()
    tenant_b = TenantId.new()
    job = make_job(tenant_id=tenant_a)
    roomy_own_node = make_node(
        tenant_id=tenant_a,
        capacity=ResourceRequirements(
            cpu_cores=64,
            memory_mib=262144,
            vram_mib=0,
        ),
    )
    # A near perfect fit for the job, but in another tenant.
    tight_foreign_node = make_node(
        tenant_id=tenant_b,
        capacity=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
    )

    chosen = Scheduler().select_node(
        job,
        [tight_foreign_node, roomy_own_node],
    )

    assert chosen is roomy_own_node


def test_the_tenant_rule_applies_per_job_in_a_mixed_fleet() -> None:
    tenant_a = TenantId.new()
    node_default = make_node()
    node_a = make_node(tenant_id=tenant_a)
    fleet = [node_default, node_a]

    assert Scheduler().select_node(make_job(), fleet) is node_default
    assert (
        Scheduler().select_node(make_job(tenant_id=tenant_a), fleet)
        is node_a
    )
    assert node_default.tenant_id == DEFAULT_TENANT_ID
