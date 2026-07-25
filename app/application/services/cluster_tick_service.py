from __future__ import annotations

import logging

from app.application.services.scheduler_loop_service import (
    SchedulerLoopService,
)
from app.application.workers.worker_execution_loop import (
    WorkerExecutionLoop,
)
from app.domain.repositories.worker_repository import (
    WorkerRepository,
)

logger = logging.getLogger(__name__)


class ClusterTickService:
    """
    Represents one full tick of the live cluster: schedule
    queued jobs onto available nodes and assign idle workers
    to them, then drive every worker that now holds a job
    through one execution-loop iteration (renew lease,
    execute, complete/fail, release lease).

    This is the single entry point the presentation layer's
    background loop calls. It exists so that driving the
    cluster forward is an explicit, named, independently
    tested use case, rather than the presentation layer
    reaching directly into repositories and orchestrating
    domain services itself.
    """

    def __init__(
        self,
        scheduler_loop_service: SchedulerLoopService,
        worker_execution_loop: WorkerExecutionLoop,
        worker_repository: WorkerRepository,
    ) -> None:
        self._scheduler_loop_service = scheduler_loop_service
        self._worker_execution_loop = worker_execution_loop
        self._worker_repository = worker_repository

    def execute(self) -> None:
        """
        Run one tick of the cluster.

        A failure driving one worker must not prevent other
        workers from being driven, and must not crash the
        background loop that calls this repeatedly, so each
        worker's execution is isolated and logged rather than
        allowed to propagate.
        """
        self._scheduler_loop_service.execute()

        for worker in self._worker_repository.list():
            if worker.running_job is None:
                continue

            try:
                self._worker_execution_loop.execute(
                    worker.id,
                )
            except Exception:
                logger.exception(
                    "Worker execution loop failed for worker %s",
                    worker.id,
                )
