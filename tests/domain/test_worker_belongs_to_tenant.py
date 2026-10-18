from __future__ import annotations

from app.domain.entities.tenant import Tenant
from tests.support.nodes import make_node
from tests.support.workers import make_worker


def test_a_worker_belongs_to_the_tenant_of_its_node() -> None:
    owner = Tenant.create("owner").id
    worker = make_worker(node=make_node(tenant_id=owner))

    assert worker.belongs_to(owner)


def test_a_worker_does_not_belong_to_another_tenant() -> None:
    owner = Tenant.create("owner").id
    other = Tenant.create("other").id
    worker = make_worker(node=make_node(tenant_id=owner))

    assert not worker.belongs_to(other)
