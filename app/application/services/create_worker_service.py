from __future__ import annotations

from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.enums.worker_management import WorkerManagement
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
from app.domain.value_objects.worker_id import WorkerId


class CreateWorkerService:
    """
    Application service responsible for registering
    a new worker for a compute node.
    """

    def __init__(
        self,
        worker_repository: WorkerRepository,
        job_repository: JobRepository,
        lease_repository: LeaseRepository,
        node_repository: NodeRepository,
    ) -> None:
        self._worker_repository = worker_repository
        self._job_repository = job_repository
        self._lease_repository = lease_repository
        self._node_repository = node_repository

    def execute(
        self,
        node: Node,
        managed_by: WorkerManagement = WorkerManagement.DASHBOARD,
    ) -> Worker:
        """
        Create and persist a worker for a node, or reclaim
        the node's existing worker if one is already
        registered (ADR 0030).

        Reclaiming preserves the existing WorkerId across an
        agent restart rather than minting a new one, using
        Worker.recover(), the same recovery path
        reconciliation already applies to abandoned work.

        Any job the existing worker was still running is fully
        reclaimed first, the same sequence reconciliation uses
        (ADR 0039): its lease is deleted, the node's allocated
        resources are released, and the job itself is reclaimed,
        before the worker is recovered. Without this, the worker
        goes IDLE while a stale lease and an unreclaimed job
        still exist, and if that worker is reassigned new work
        before the old lease expires, the old lease's eventual
        expiry would corrupt the new job's tracking instead.
        """
        existing = self._worker_repository.get_by_node_id(
            node.id,
        )

        if existing is not None:
            abandoned_job = existing.running_job

            if abandoned_job is not None:
                self._lease_repository.delete(
                    abandoned_job.id,
                )

                node.release(
                    abandoned_job.resources,
                )
                self._node_repository.save(
                    node,
                )

                abandoned_job.reclaim()
                self._job_repository.save(
                    abandoned_job,
                )

            existing.recover()
            existing.managed_by = managed_by

            self._worker_repository.save(
                existing,
            )

            return existing

        worker = Worker(
            id=WorkerId.new(),
            node=node,
            managed_by=managed_by,
        )

        worker.ready()

        self._worker_repository.save(
            worker,
        )

        return worker
