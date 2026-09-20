from datetime import UTC, datetime, timedelta

from app.application.reconciliation.reconciliation_loop import (
    ReconciliationLoop,
)
from app.application.reconciliation.recover_expired_lease_service import (
    RecoverExpiredLeaseService,
)
from app.application.reconciliation.recover_offline_node_service import (
    RecoverOfflineNodeService,
)
from app.application.services.mark_dead_workers_service import (
    MarkDeadWorkersService,
)
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
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


def test_stale_jobless_worker_on_stale_node_stays_offline_across_cycles() -> (
    None
):
    """
    Interaction regression test. MarkDeadWorkersService marks a
    stale worker OFFLINE, and RecoverOfflineNodeService, running
    later in the same cycle, used to reset that worker to IDLE
    because its node was also stale. OFFLINE was overwritten on
    every cycle and never observable. This wires the real
    services over shared repositories, the way dependencies.py
    does, and runs several cycles.
    """
    stale = datetime.now(UTC) - timedelta(minutes=5)

    node = Node(
        id=NodeId.new(),
        capacity=ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=0,
        ),
    )
    node.last_seen_at = stale

    worker = Worker(
        id=WorkerId.new(),
        node=node,
    )
    worker.ready()
    worker.last_seen_at = stale

    node_repository = InMemoryNodeRepository([node])
    worker_repository = InMemoryWorkerRepository([worker])
    job_repository = InMemoryJobRepository([])
    lease_repository = InMemoryLeaseRepository()

    loop = ReconciliationLoop(
        mark_dead_workers_service=MarkDeadWorkersService(
            worker_repository=worker_repository,
        ),
        recover_expired_lease_service=RecoverExpiredLeaseService(
            worker_repository=worker_repository,
            job_repository=job_repository,
            lease_repository=lease_repository,
            node_repository=node_repository,
        ),
        recover_offline_node_service=RecoverOfflineNodeService(
            node_repository=node_repository,
            worker_repository=worker_repository,
            job_repository=job_repository,
            lease_repository=lease_repository,
        ),
    )

    for _ in range(3):
        loop.execute()

        stored = worker_repository.get_by_id(worker.id)

        assert stored is not None
        assert stored.status.value == "OFFLINE"
