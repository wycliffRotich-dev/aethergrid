from __future__ import annotations

from app.domain.entities.lease import Lease
from app.domain.repositories.lease_repository import (
    LeaseRepository,
)
from app.domain.value_objects.worker_id import WorkerId


class GetLeaseForWorkerService:
    """
    Application service responsible for retrieving the lease
    a worker currently holds, if any.

    Exists so the presentation layer can expose lease_id on
    worker-facing responses (ADR 0036) without reaching into
    LeaseRepository directly, keeping the same discipline
    every other repository in this codebase already follows:
    routers call services, never repositories.
    """

    def __init__(
        self,
        lease_repository: LeaseRepository,
    ) -> None:
        self._lease_repository = lease_repository

    def execute(
        self,
        worker_id: WorkerId,
    ) -> Lease | None:
        """
        Retrieve the lease currently held by a worker.

        Returns:
            The lease if the worker holds one, otherwise
            None.
        """
        return self._lease_repository.get_by_worker_id(
            worker_id,
        )
