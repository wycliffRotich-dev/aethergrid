from __future__ import annotations

from typing import Any

import pytest

from app.domain.entities.lease import Lease
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId


def test_a_lease_carries_the_tenant_it_was_created_with() -> None:
    tenant = TenantId.new()

    lease = Lease.create(
        worker_id=WorkerId.new(),
        job_id=JobId.new(),
        tenant_id=tenant,
    )

    assert lease.tenant_id == tenant


def test_a_lease_cannot_be_created_without_a_tenant() -> None:
    arguments: dict[str, Any] = {
        "worker_id": WorkerId.new(),
        "job_id": JobId.new(),
    }

    with pytest.raises(TypeError):
        Lease.create(**arguments)
