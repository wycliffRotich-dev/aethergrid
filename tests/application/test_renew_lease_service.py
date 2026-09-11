from datetime import timedelta
from uuid import uuid4

import pytest

from app.application.services.renew_lease_service import (
    RenewLeaseService,
)
from app.domain.entities.job import Job
from app.domain.entities.lease import Lease
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.exceptions.lease_not_found_error import (
    LeaseNotFoundError,
)
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
        expected_lease_id=lease.id,
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
        service.execute(
            WorkerId.new(),
            expected_lease_id=uuid4(),
        )


def test_execute_rejects_renewal_when_lease_reassigned_to_different_job() -> None:
    """
    ADR 0038: proves the fenced renewal rejects a stale
    caller's attempt to renew a lease that has since moved on
    to a different job. Before this fix, RenewLeaseService
    resolved "the lease" by worker_id alone, so a stale caller
    still holding an old lease's identity would have silently
    renewed whatever lease is currently on record for that
    worker instead of the one it actually started with.
    """
    repository = InMemoryLeaseRepository()

    worker_id = WorkerId.new()

    original_lease = Lease.create(
        worker_id=worker_id,
        job_id=JobId.new(),
        duration=timedelta(minutes=1),
    )
    repository.save(original_lease)

    # Reconciliation reclaims the original lease.
    repository.delete(original_lease.job_id)

    # The same worker is legitimately reassigned a new job,
    # with its own new lease.
    replacement_lease = Lease.create(
        worker_id=worker_id,
        job_id=JobId.new(),
        duration=timedelta(minutes=1),
    )
    repository.save(replacement_lease)

    replacement_original_expiration = replacement_lease.expires_at

    service = RenewLeaseService(
        lease_repository=repository,
    )

    # The stale caller, still believing it holds original_lease,
    # is rejected: whatever lease is on record for this worker
    # (replacement_lease) does not match expected_lease_id, so
    # nothing gets renewed on its behalf (ADR 0038).
    with pytest.raises(LeaseNotFoundError):
        service.execute(
            worker_id,
            expected_lease_id=original_lease.id,
            duration=timedelta(minutes=5),
        )

    # The replacement lease must survive untouched -- not
    # renewed, not deleted.
    surviving = repository.get_by_worker_id(worker_id)

    assert surviving is not None
    assert surviving.id == replacement_lease.id
    assert surviving.expires_at == replacement_original_expiration
