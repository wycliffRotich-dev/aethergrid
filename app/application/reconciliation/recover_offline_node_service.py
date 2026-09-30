from __future__ import annotations

from app.application.services.job_execution_support import (
    reclaim_job,
)
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

    Node heartbeat and lease renewal are independent signals
    (ADR 0052 follow-up, issue #267): a worker's lease-renewal
    thread and its node's heartbeat run on separate schedules,
    in both WorkerExecutionLoop and the standalone agent, with
    no coupling between them. A node can go offline on a
    missed heartbeat while its worker's lease is still being
    actively, successfully renewed. Reclaiming unconditionally
    on node liveness alone would steal that live lease out
    from under a worker doing real, ongoing work. This service
    now checks the job's own lease before reclaiming: no lease
    or an actually-expired one proceeds as before; a lease
    that is still valid is left untouched, and the worker is
    not marked recovered, since it may still be legitimately
    executing.
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

            # A worker with no job has nothing to recover here.
            # Resetting it would overwrite the OFFLINE status
            # MarkDeadWorkersService just set for a stale
            # heartbeat. ADR 0041 leaves a jobless OFFLINE
            # worker OFFLINE until a heartbeat proves it is back.
            if job is None:
                continue

            lease = self._lease_repository.get_by_job_id(
                job.id,
            )

            lease_already_deleted = False

            if lease is not None:
                if not lease.is_expired():
                    # The node's heartbeat lapsed, but this
                    # worker's lease is still being actively
                    # renewed -- it is still legitimately doing
                    # work. Reclaiming here would steal a live
                    # lease out from under its current owner,
                    # the same race ADR 0052 closed for expired
                    # leases. Leave the worker's status alone
                    # too: it may still be OFFLINE-but-working,
                    # not actually abandoned.
                    continue

                deleted = self._lease_repository.delete_if_expired(
                    job.id,
                )

                if not deleted:
                    # Renewed between the check above and this
                    # delete -- same race, caught at the last
                    # possible moment instead of the first.
                    continue

                lease_already_deleted = True

            node = worker.node

            worker.recover()

            self._worker_repository.save(
                worker,
            )

            reclaimed = reclaim_job(
                job,
                node,
                lease_repository=self._lease_repository,
                node_repository=self._node_repository,
                job_repository=self._job_repository,
                lease_already_deleted=lease_already_deleted,
            )

            if (
                reclaimed
                and self._record_job_events_service is not None
            ):
                self._record_job_events_service.record(
                    aggregate_id=str(job.id),
                    event_type="JobReclaimed",
                )
