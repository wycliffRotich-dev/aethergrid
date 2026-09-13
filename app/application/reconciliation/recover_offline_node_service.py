from __future__ import annotations

from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.repositories.job_repository import (
    JobRepository,
)
from app.domain.repositories.lease_repository import (
    LeaseRepository,
)
from app.domain.repositories.node_repository import (
    NodeRepository,
)
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)


class RecoverOfflineNodeService:
    """
    Recover work abandoned by offline nodes.

    Nodes are considered offline when they stop
    sending heartbeats. Any scheduled or running work
    assigned to workers on those nodes is reclaimed,
    consuming a retry attempt, rather than simply
    returned to the queue as-is.

    The job's lease row is deleted here too, before
    reclaim() runs, mirroring RecoverExpiredLeaseService's
    exact pattern (ADR 0034 follow-up): without this, a
    reclaimed job's stale lease survives, and the very next
    attempt to reschedule it -- AcquireLeaseService checking
    get_by_job_id() -- finds that stale row and refuses to
    acquire a new lease, permanently stranding the job. This
    was independently rediscovered here, the same way the
    RUNNING-persistence gap (ADR 0033) was found twice in
    separate execution paths before being fixed at the root.
    """

    def __init__(
        self,
        node_repository: NodeRepository,
        worker_repository: WorkerRepository,
        job_repository: JobRepository,
        lease_repository: LeaseRepository,
        record_job_events_service: RecordJobEventsService | None = None,
    ) -> None:
        self._node_repository = node_repository
        self._worker_repository = worker_repository
        self._job_repository = job_repository
        self._lease_repository = lease_repository
        self._record_job_events_service = record_job_events_service

    def execute(
        self,
    ) -> None:
        """
        Recover jobs assigned to offline nodes.
        """
        offline_node_ids = {
            node.id
            for node in self._node_repository.list()
            if not node.is_alive()
        }

        if not offline_node_ids:
            return

        for worker in self._worker_repository.list():

            if worker.node.id not in offline_node_ids:
                continue

            job = worker.running_job
            node = worker.node

            worker.recover()

            self._worker_repository.save(
                worker,
            )

            if job is None:
                continue

            self._lease_repository.delete(
                job.id,
            )

            node.release(job.resources)

            self._node_repository.save(
                node,
            )

            job.reclaim()

            self._job_repository.save(
                job,
            )

            if self._record_job_events_service is not None:
                self._record_job_events_service.record(
                    aggregate_id=str(job.id),
                    event_type="JobReclaimed",
                )
