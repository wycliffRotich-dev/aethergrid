from datetime import timedelta
from uuid import uuid4

import pytest

from app.application.services.renew_lease_service import (
    RenewLeaseService,
)
from app.domain.entities.lease import Lease
from app.domain.entities.tenant import DEFAULT_TENANT_ID
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
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_lease_repository import (
    InMemoryLeaseRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node
from tests.support.workers import make_worker


def test_execute_renews_worker_lease() -> None:
    node = make_node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )

    worker = make_worker(
        id=WorkerId.new(),
        node=node,
    )

    job = make_job(
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
        tenant_id=worker.tenant_id,
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
        tenant_id=worker.tenant_id,
        duration=timedelta(minutes=5),
    )

    renewed = repository.get_by_worker_id(
        worker.id,
        worker.tenant_id,
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
            tenant_id=DEFAULT_TENANT_ID,
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
        tenant_id=DEFAULT_TENANT_ID,
        duration=timedelta(minutes=1),
    )
    repository.save(original_lease)

    # Reconciliation reclaims the original lease.
    repository.delete(original_lease.job_id, original_lease.tenant_id)

    # The same worker is legitimately reassigned a new job,
    # with its own new lease.
    replacement_lease = Lease.create(
        worker_id=worker_id,
        job_id=JobId.new(),
        tenant_id=DEFAULT_TENANT_ID,
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
            tenant_id=DEFAULT_TENANT_ID,
            duration=timedelta(minutes=5),
        )

    # The replacement lease must survive untouched -- not
    # renewed, not deleted.
    surviving = repository.get_by_worker_id(worker_id, DEFAULT_TENANT_ID)

    assert surviving is not None
    assert surviving.id == replacement_lease.id
    assert surviving.expires_at == replacement_original_expiration


def test_execute_does_not_renew_a_lease_in_another_tenant() -> None:
    """
    ADR 0075: a worker's lease in another tenant is reported exactly
    like a missing one, and its expiry does not move.
    """
    repository = InMemoryLeaseRepository()
    tenant = TenantId.new()
    lease = Lease.create(
        worker_id=WorkerId.new(),
        job_id=JobId.new(),
        tenant_id=tenant,
        duration=timedelta(minutes=1),
    )
    repository.save(lease)
    expiry_before = lease.expires_at

    service = RenewLeaseService(
        lease_repository=repository,
    )

    with pytest.raises(NoActiveLeaseError):
        service.execute(
            lease.worker_id,
            expected_lease_id=lease.id,
            tenant_id=TenantId.new(),
            duration=timedelta(minutes=5),
        )

    surviving = repository.get_by_worker_id(lease.worker_id, tenant)

    assert surviving is not None
    assert surviving.expires_at == expiry_before
