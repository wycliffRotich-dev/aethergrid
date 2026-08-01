from __future__ import annotations

from app.application.services.record_job_events_service import (
    RecordJobEventsService,
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


class RecoverOfflineNodeService:
    """
    Recover work abandoned by offline nodes.

    Nodes are considered offline when they stop
    sending heartbeats. Any scheduled or running work
    assigned to workers on those nodes is reclaimed,
    consuming a retry attempt, rather than simply
    returned to the queue as-is.
    """

    def __init__(
        self,
        node_repository: NodeRepository,
        worker_repository: WorkerRepository,
        job_repository: JobRepository,
        record_job_events_service: RecordJobEventsService | None = None,
    ) -> None:
        self._node_repository = node_repository
        self._worker_repository = worker_repository
        self._job_repository = job_repository
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

            worker.recover()

            self._worker_repository.save(
                worker,
            )

            if job is None:
                continue

            job.reclaim()

            self._job_repository.save(
                job,
            )

            if self._record_job_events_service is not None:
                self._record_job_events_service.record(
                    aggregate_id=str(job.id),
                    event_type="JobReclaimed",
                )
