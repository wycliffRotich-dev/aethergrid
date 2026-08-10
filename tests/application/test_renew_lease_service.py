from datetime import timedelta

import pytest

from app.application.services.renew_lease_service import (
    RenewLeaseService,
)
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.exceptions.no_active_lease_error import (
    NoActiveLeaseError,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_lease_repository import (
    InMemoryLeaseRepository,
)


def test_execute_renews_worker_lease() -> None:
    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = Worker(
        id=WorkerId.new(),
        node=node,
    )

    job = Job(
        id=JobId.new(),
        resources=ResourceRequirements(
            cpu_cores=1,
            memory_mib=512,
            vram_mib=0,
        ),
    )

    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
        duration=timedelta(minutes=1),
    )

    original_expiration = lease.expires_at

    repository = InMemoryLeaseRepository()

    repository.save(
        lease,
    )

    service = RenewLeaseService(
        lease_repository=repository,
    )

    service.execute(
        worker.id,
        duration=timedelta(minutes=5),
    )

    renewed = repository.get_by_worker_id(
        worker.id,
    )

    assert renewed is not None
    assert renewed.expires_at > original_expiration


def test_execute_raises_when_worker_has_no_active_lease() -> None:
    """
    A worker that never acquired a lease, or whose lease was
    already reclaimed by reconciliation before this call even
    looked it up, must raise NoActiveLeaseError -- not silently
    no-op, and not create a fresh lease out of nothing.
    """
    repository = InMemoryLeaseRepository()

    service = RenewLeaseService(
        lease_repository=repository,
    )

    with pytest.raises(NoActiveLeaseError):
        service.execute(WorkerId.new())
