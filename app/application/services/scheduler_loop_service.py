from __future__ import annotations

from app.application.services.assign_worker_service import (
    AssignWorkerService,
)
from app.application.services.record_job_events_service import (
    RecordJobEventsService,
)
from app.domain.enums.job_status import JobStatus
from app.domain.exceptions.no_available_node_error import (
    NoAvailableNodeError,
)
from app.domain.repositories.job_repository import (
    JobRepository,
)
from app.domain.repositories.node_repository import (
    NodeRepository,
)
from app.domain.services.scheduler import Scheduler


class SchedulerLoopService:
    """
    Application service responsible for scheduling queued jobs
    onto healthy nodes and assigning workers.
    """

    def __init__(
        self,
        job_repository: JobRepository,
        node_repository: NodeRepository,
        scheduler: Scheduler,
        assign_worker_service: AssignWorkerService | None = None,
        record_job_events_service: RecordJobEventsService | None = None,
    ) -> None:
        self._job_repository = job_repository
        self._node_repository = node_repository
        self._scheduler = scheduler
        self._assign_worker_service = assign_worker_service
        self._record_job_events_service = record_job_events_service

    def execute(
        self,
    ) -> None:
        """
        Schedule queued jobs in priority order.
        """
        nodes = self._node_repository.list_available_across_tenants()

        queued_jobs = sorted(
            (
                job
                for job in self._job_repository.list_across_tenants()
                if job.status == JobStatus.QUEUED
            ),
            key=lambda job: job.priority,
            reverse=True,
        )

        for job in queued_jobs:
            node = self._scheduler.select_node(
                job,
                nodes,
            )

            if node is None:
                continue

            allocated = self._node_repository.allocate(
                node.id,
                node.tenant_id,
                job.resources,
            )

            if not allocated:
                # The node's available capacity changed after the
                # snapshot above (another writer allocated), so this
                # node can no longer host the job. Leave it QUEUED;
                # the next tick re-selects it (ADR 0105).
                continue

            # Refresh this node in the snapshot so later jobs in this
            # tick see its remaining capacity. The snapshot was read
            # before this allocation, so on backends that reconstruct
            # nodes on read (Postgres, SQLite) it is stale here, and a
            # later job would otherwise be matched to a node this one
            # just filled (ADR 0105).
            refreshed = self._node_repository.get_by_id(
                node.id,
                node.tenant_id,
            )

            if refreshed is not None:
                for index, candidate in enumerate(nodes):
                    if candidate.id == node.id:
                        nodes[index] = refreshed
                        break

            job.assign_to(
                node.id,
            )

            self._job_repository.save(
                job,
            )

            if self._record_job_events_service is not None:
                self._record_job_events_service.record_for_job(
                    job,
                    event_type="JobScheduled",
                )

            if self._assign_worker_service is not None:
                try:
                    self._assign_worker_service.execute(
                        job,
                    )
                except NoAvailableNodeError:
                    # The node had capacity, but no idle worker was
                    # registered on it yet (e.g. an agent hadn't
                    # finished starting up). The job was already
                    # saved as SCHEDULED above, which permanently
                    # removes it from this method's own QUEUED
                    # filter -- without this, it would never be
                    # revisited by any future tick, even once a
                    # worker does become available. Undo the
                    # scheduling decision and give the node's
                    # capacity back so the job is retried on the
                    # very next tick instead of being stranded.
                    job.unschedule()
                    self._node_repository.release(
                        node.id,
                        node.tenant_id,
                        job.resources,
                    )
                    self._job_repository.save(
                        job,
                    )
                    if self._record_job_events_service is not None:
                        self._record_job_events_service.record_for_job(
                            job,
                            event_type="JobUnscheduled",
                        )
