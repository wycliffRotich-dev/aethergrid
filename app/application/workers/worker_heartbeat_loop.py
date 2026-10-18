from __future__ import annotations

from app.application.services.worker_heartbeat_service import (
    WorkerHeartbeatService,
)
from app.domain.value_objects.tenant_id import TenantId
from app.domain.value_objects.worker_id import WorkerId


class WorkerHeartbeatLoop:
    """
    Periodically publishes worker heartbeats.
    """

    def __init__(
        self,
        heartbeat_service: WorkerHeartbeatService,
        worker_id: WorkerId,
        tenant_id: TenantId,
    ) -> None:
        self._heartbeat_service = heartbeat_service
        self._worker_id = worker_id
        self._tenant_id = tenant_id

    def run_once(
        self,
    ) -> None:
        """
        Execute a single heartbeat iteration.
        """
        self._heartbeat_service.execute(
            self._worker_id,
            self._tenant_id,
        )
