from __future__ import annotations

from datetime import timedelta

from app.application.reconciliation.recover_expired_lease_service import (
    RecoverExpiredLeaseService,
)
from app.application.services.cancel_job_service import (
    CancelJobService,
)
from app.domain.entities.lease import Lease
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from app.infrastructure.repositories.in_memory_lease_repository import (
    InMemoryLeaseRepository,
)
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)
from tests.support.jobs import make_job
from tests.support.nodes import make_node
from tests.support.workers import make_worker


def test_cancelled_scheduled_job_gets_its_node_capacity_back() -> None:
    """
    A SCHEDULED job holds node capacity, a lease and a BUSY
    worker. CancelJobService cancels it with a status change
    and a save, so nothing releases that capacity at cancel
    time. Reconciliation is the only thing that gives it back,
    once the lease expires. The node must end up fully free,
    and the job must stay CANCELLED, not be requeued.
    """
    capacity = ResourceRequirements(
        cpu_cores=8,
        memory_mib=16384,
        vram_mib=0,
    )
    resources = ResourceRequirements(
        cpu_cores=1,
        memory_mib=512,
        vram_mib=0,
    )

    node = make_node(id=NodeId.new(), capacity=capacity)
    worker = make_worker(id=WorkerId.new(), node=node)
    worker.ready()

    job = make_job(
        id=JobId.new(),
        resources=resources,
        max_retries=1,
    )
    job.queue()
    node.allocate(resources)
    job.assign_to(node.id)
    worker.accept(job)

    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
        tenant_id=worker.tenant_id,
        duration=timedelta(seconds=-1),
    )

    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])
    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)
    node_repository = InMemoryNodeRepository([node])

    cancelled = CancelJobService(
        job_repository=job_repository,
    ).execute(job.id, DEFAULT_TENANT_ID)

    assert cancelled is not None
    assert cancelled.is_cancelled()

    RecoverExpiredLeaseService(
        worker_repository=worker_repository,
        job_repository=job_repository,
        lease_repository=lease_repository,
        node_repository=node_repository,
    ).execute()

    reloaded_node = node_repository.get_by_id(
        node.id, DEFAULT_TENANT_ID
    )
    reloaded_job = job_repository.get_by_id(job.id, DEFAULT_TENANT_ID)

    assert reloaded_job is not None
    assert reloaded_job.is_cancelled()
    assert reloaded_node is not None
    assert reloaded_node.available == capacity


def test_cancelled_scheduled_job_is_credited_exactly_once() -> None:
    """
    The node also hosts another allocation, so it is never fully
    free. Crediting the cancelled job twice would make the node
    report capacity that the other allocation still holds, and
    the clamp at full capacity would not hide it.
    """
    capacity = ResourceRequirements(
        cpu_cores=8,
        memory_mib=16384,
        vram_mib=0,
    )
    resources = ResourceRequirements(
        cpu_cores=1,
        memory_mib=512,
        vram_mib=0,
    )
    other_allocation = ResourceRequirements(
        cpu_cores=2,
        memory_mib=1024,
        vram_mib=0,
    )

    node = make_node(id=NodeId.new(), capacity=capacity)
    worker = make_worker(id=WorkerId.new(), node=node)
    worker.ready()

    job = make_job(
        id=JobId.new(),
        resources=resources,
        max_retries=1,
    )
    job.queue()
    node.allocate(resources)
    node.allocate(other_allocation)
    job.assign_to(node.id)
    worker.accept(job)

    lease = Lease.create(
        worker_id=worker.id,
        job_id=job.id,
        tenant_id=worker.tenant_id,
        duration=timedelta(seconds=-1),
    )

    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([job])
    lease_repository = InMemoryLeaseRepository()
    lease_repository.save(lease)
    node_repository = InMemoryNodeRepository([node])

    CancelJobService(
        job_repository=job_repository,
    ).execute(job.id, DEFAULT_TENANT_ID)

    RecoverExpiredLeaseService(
        worker_repository=worker_repository,
        job_repository=job_repository,
        lease_repository=lease_repository,
        node_repository=node_repository,
    ).execute()

    reloaded_node = node_repository.get_by_id(
        node.id, DEFAULT_TENANT_ID
    )

    assert reloaded_node is not None
    assert reloaded_node.available == ResourceRequirements(
        cpu_cores=6,
        memory_mib=15360,
        vram_mib=0,
    )
