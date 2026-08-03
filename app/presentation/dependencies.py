from __future__ import annotations

import os

from app.application.reconciliation.reconciliation_loop import (
    ReconciliationLoop,
)
from app.application.reconciliation.recover_expired_lease_service import (
    RecoverExpiredLeaseService,
)
from app.application.reconciliation.recover_offline_node_service import (
    RecoverOfflineNodeService,
)
from app.application.services.acquire_lease_service import (
    AcquireLeaseService,
)
from app.application.services.assign_worker_service import (
    AssignWorkerService,
)
from app.application.services.cancel_job_service import (
    CancelJobService,
)
from app.application.services.cluster_capacity_service import (
    ClusterCapacityService,
)
from app.application.services.cluster_health_service import (
    ClusterHealthService,
)
from app.application.services.cluster_tick_service import (
    ClusterTickService,
)
from app.application.services.cluster_utilization_service import (
    ClusterUtilizationService,
)
from app.application.services.create_job_service import (
    CreateJobService,
)
from app.application.services.create_node_service import (
    CreateNodeService,
)
from app.application.services.create_worker_service import (
    CreateWorkerService,
)
from app.application.services.drain_node_service import (
    DrainNodeService,
)
from app.application.services.get_job_history_service import (
    GetJobHistoryService,
)
from app.application.services.get_job_service import (
    GetJobService,
)
from app.application.services.get_node_service import (
    GetNodeService,
)
from app.application.services.heartbeat_node_service import (
    HeartbeatNodeService,
)
from app.application.services.job_execution_service import (
    JobExecutionService,
)
from app.application.services.list_events_service import (
    ListEventsService,
)
from app.application.services.list_jobs_service import (
    ListJobsService,
)
from app.application.services.list_nodes_service import (
    ListNodesService,
)
from app.application.services.list_offline_nodes_service import (
    ListOfflineNodesService,
)
from app.application.services.list_queued_jobs_service import (
    ListQueuedJobsService,
)
from app.application.services.list_workers_service import (
    ListWorkersService,
)
from app.application.services.mark_dead_workers_service import (
    MarkDeadWorkersService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.application.services.register_worker_service import (
    RegisterWorkerService,
)
from app.application.services.release_lease_service import (
    ReleaseLeaseService,
)
from app.application.services.remove_offline_node_service import (
    RemoveOfflineNodeService,
)
from app.application.services.renew_lease_service import (
    RenewLeaseService,
)
from app.application.services.retry_job_service import (
    RetryJobService,
)
from app.application.services.scheduler_loop_service import (
    SchedulerLoopService,
)
from app.application.services.worker_heartbeat_service import (
    WorkerHeartbeatService,
)
from app.application.workers.worker_execution_loop import (
    WorkerExecutionLoop,
)
from app.domain.repositories.event_repository import (
    EventRepository,
)
from app.domain.repositories.job_repository import (
    JobRepository,
)
from app.domain.repositories.node_repository import (
    NodeRepository,
)
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)
from app.domain.services.scheduler import Scheduler
from app.infrastructure.repositories.in_memory_event_repository import (
    InMemoryEventRepository,
)
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
from app.infrastructure.repositories.sqlite_connection import (
    create_connection,
)
from app.infrastructure.repositories.sqlite_event_repository import (
    SqliteEventRepository,
)
from app.infrastructure.repositories.sqlite_job_repository import (
    SqliteJobRepository,
)
from app.infrastructure.repositories.sqlite_node_repository import (
    SqliteNodeRepository,
)


def _build_repositories() -> tuple[
    JobRepository,
    NodeRepository,
    WorkerRepository,
    EventRepository,
]:
    """
    Choose the repository backend.
    """

    backend = os.getenv(
        "NEUROMESH_STORAGE_BACKEND",
        "memory",
    ).lower()

    if backend == "sqlite":
        db_path = os.getenv(
            "NEUROMESH_DB_PATH",
            "neuromesh.db",
        )

        connection = create_connection(
            db_path,
        )

        return (
            SqliteJobRepository(
                connection,
            ),
            SqliteNodeRepository(
                connection,
            ),
            InMemoryWorkerRepository(),
            SqliteEventRepository(
                connection,
            ),
        )

    return (
        InMemoryJobRepository(),
        InMemoryNodeRepository(),
        InMemoryWorkerRepository(),
        InMemoryEventRepository(),
    )


(
    _job_repository,
    _node_repository,
    _worker_repository,
    _event_repository,
) = _build_repositories()


# Lease has no SQLite implementation, only in-memory and
# PostgreSQL (see ADR 0010). This mirrors the existing
# precedent already set for Worker above: both use the
# in-memory implementation regardless of the selected
# backend, since neither has a SQLite repository today.
_lease_repository = InMemoryLeaseRepository()


_record_job_events_service = RecordJobEventsService(
    event_repository=_event_repository,
)


_acquire_lease_service = AcquireLeaseService(
    lease_repository=_lease_repository,
    record_job_events_service=_record_job_events_service,
)

_renew_lease_service = RenewLeaseService(
    lease_repository=_lease_repository,
)


_release_lease_service = ReleaseLeaseService(
    lease_repository=_lease_repository,
    worker_repository=_worker_repository,
    record_job_events_service=_record_job_events_service,
)
_assign_worker_service = AssignWorkerService(
    worker_repository=_worker_repository,
    acquire_lease_service=_acquire_lease_service,
    record_job_events_service=_record_job_events_service,
)

_register_worker_service = RegisterWorkerService(
    worker_repository=_worker_repository,
)


_job_execution_service = JobExecutionService()


_worker_execution_loop = WorkerExecutionLoop(
    worker_repository=_worker_repository,
    job_repository=_job_repository,
    node_repository=_node_repository,
    renew_lease_service=_renew_lease_service,
    release_lease_service=_release_lease_service,
    job_execution_service=_job_execution_service,
    record_job_events_service=_record_job_events_service,
)

_domain_scheduler = Scheduler()


_scheduler_loop_service = SchedulerLoopService(
    job_repository=_job_repository,
    node_repository=_node_repository,
    scheduler=_domain_scheduler,
    assign_worker_service=_assign_worker_service,
    record_job_events_service=_record_job_events_service,
)

_cluster_tick_service = ClusterTickService(
    scheduler_loop_service=_scheduler_loop_service,
    worker_execution_loop=_worker_execution_loop,
    worker_repository=_worker_repository,
)
_mark_dead_workers_service = MarkDeadWorkersService(
    worker_repository=_worker_repository,
)
_recover_expired_lease_service = RecoverExpiredLeaseService(
    worker_repository=_worker_repository,
    job_repository=_job_repository,
    lease_repository=_lease_repository,
    record_job_events_service=_record_job_events_service,
)
_recover_offline_node_service = RecoverOfflineNodeService(
    node_repository=_node_repository,
    worker_repository=_worker_repository,
    job_repository=_job_repository,
    record_job_events_service=_record_job_events_service,
)
_reconciliation_loop = ReconciliationLoop(
    mark_dead_workers_service=_mark_dead_workers_service,
    recover_expired_lease_service=_recover_expired_lease_service,
    recover_offline_node_service=_recover_offline_node_service,
)


def get_reconciliation_loop() -> ReconciliationLoop:
    """
    Return the ReconciliationLoop, the single entry point for
    detecting and repairing state left inconsistent by dead
    workers, expired leases, and offline nodes.
    """
    return _reconciliation_loop

def get_create_job_service() -> CreateJobService:
    """
    Return CreateJobService.
    """

    return CreateJobService(
        job_repository=_job_repository,
        record_job_events_service=_record_job_events_service,
    )


def get_get_job_service() -> GetJobService:
    """
    Return GetJobService.
    """

    return GetJobService(
        job_repository=_job_repository,
    )

def get_retry_job_service() -> RetryJobService:
    """
    Return RetryJobService.
    """

    return RetryJobService(
        job_repository=_job_repository,
    )

def get_cancel_job_service() -> CancelJobService:
    """
    Return CancelJobService.
    """

    return CancelJobService(
        job_repository=_job_repository,
    )

def get_worker_heartbeat_service() -> WorkerHeartbeatService:
    """
    Return WorkerHeartbeatService.
    """

    return WorkerHeartbeatService(
        worker_repository=_worker_repository,
    )

def get_get_job_history_service() -> GetJobHistoryService:
    """
    Return GetJobHistoryService.
    """

    return GetJobHistoryService(
        event_repository=_event_repository,
    )


def get_list_queued_jobs_service() -> ListQueuedJobsService:
    """
    Return ListQueuedJobsService.
    """

    return ListQueuedJobsService(
        job_repository=_job_repository,
    )


def get_list_jobs_service() -> ListJobsService:
    """
    Return ListJobsService.
    """

    return ListJobsService(
        job_repository=_job_repository,
    )


def get_list_workers_service() -> ListWorkersService:
    """
    Return ListWorkersService.
    """

    return ListWorkersService(
        worker_repository=_worker_repository,
    )


def get_record_job_events_service() -> RecordJobEventsService:
    """
    Return RecordJobEventsService.
    """

    return _record_job_events_service

def get_list_events_service() -> ListEventsService:
    """
    Return ListEventsService.
    """

    return ListEventsService(
        event_repository=_event_repository,
    )
def get_list_offline_nodes_service() -> ListOfflineNodesService:
    """
    Return ListOfflineNodesService.
    """

    return ListOfflineNodesService(
        node_repository=_node_repository,
    )


def get_create_node_service() -> CreateNodeService:
    """
    Return CreateNodeService.
    """

    return CreateNodeService(
        node_repository=_node_repository,
    )


def get_get_node_service() -> GetNodeService:
    """
    Return GetNodeService.
    """

    return GetNodeService(
        node_repository=_node_repository,
    )
def get_remove_offline_node_service() -> RemoveOfflineNodeService:
    """
    Return RemoveOfflineNodeService.
    """

    return RemoveOfflineNodeService(
        node_repository=_node_repository,
    )
def get_drain_node_service() -> DrainNodeService:
    """
    Return DrainNodeService.
    """

    return DrainNodeService(
        node_repository=_node_repository,
    )

def get_cluster_utilization_service() -> ClusterUtilizationService:
    """
    Return ClusterUtilizationService.
    """

    return ClusterUtilizationService(
        node_repository=_node_repository,
    )


def get_heartbeat_node_service() -> HeartbeatNodeService:
    """
    Return HeartbeatNodeService.
    """

    return HeartbeatNodeService(
        node_repository=_node_repository,
    )


def get_list_nodes_service() -> ListNodesService:
    """
    Return ListNodesService.
    """

    return ListNodesService(
        node_repository=_node_repository,
    )


def get_cluster_health_service() -> ClusterHealthService:
    """
    Return ClusterHealthService.
    """

    return ClusterHealthService(
        node_repository=_node_repository,
    )


def get_cluster_capacity_service() -> ClusterCapacityService:
    """
    Return ClusterCapacityService.
    """

    return ClusterCapacityService(
        node_repository=_node_repository,
    )


def get_create_worker_service() -> CreateWorkerService:
    """
    Return CreateWorkerService.
    """

    return CreateWorkerService(
        worker_repository=_worker_repository,
    )


def get_register_worker_service() -> RegisterWorkerService:
    """
    Return RegisterWorkerService.
    """

    return RegisterWorkerService(
        worker_repository=_worker_repository,
    )


def get_cluster_tick_service() -> ClusterTickService:
    """
    Return the ClusterTickService, the single entry point
    the background loop calls to drive the cluster forward.
    """

    return _cluster_tick_service
