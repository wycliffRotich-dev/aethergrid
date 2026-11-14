from __future__ import annotations

import logging
from collections.abc import Callable

from app.application.reconciliation.recover_expired_lease_service import (
    RecoverExpiredLeaseService,
)
from app.application.reconciliation.recover_leaseless_job_service import (
    RecoverLeaselessJobService,
)
from app.application.reconciliation.recover_offline_node_service import (
    RecoverOfflineNodeService,
)
from app.application.services.mark_dead_workers_service import (
    MarkDeadWorkersService,
)

logger = logging.getLogger(__name__)


class ReconciliationLoop:
    """
    Executes one reconciliation cycle.

    The reconciliation loop inspects the current state of the
    worker fleet, active leases, and node liveness. It does not
    decide how to repair inconsistencies itself, it delegates
    each concern to a dedicated recovery service and simply
    runs them in a fixed, predictable order each cycle.
    """

    def __init__(
        self,
        mark_dead_workers_service: MarkDeadWorkersService,
        recover_expired_lease_service: RecoverExpiredLeaseService,
        recover_offline_node_service: RecoverOfflineNodeService,
        recover_leaseless_job_service: RecoverLeaselessJobService,
    ) -> None:
        self._mark_dead_workers_service = mark_dead_workers_service
        self._recover_expired_lease_service = recover_expired_lease_service
        self._recover_offline_node_service = recover_offline_node_service
        self._recover_leaseless_job_service = recover_leaseless_job_service

    def execute(
        self,
    ) -> None:
        """
        Execute one reconciliation iteration.

        Dead workers are marked offline first, so their status
        is accurate before the recovery services below run.
        Marking a worker offline here does not by itself
        reclaim its job -- that still happens through lease
        expiry, since a dead worker's execution loop has
        stopped renewing. This step exists to keep worker
        status honest for the dashboard and cluster health
        reporting, not as a second reclaim path.

        Expired leases are reclaimed next so that a job
        abandoned by a dead worker is freed before offline-node
        recovery re-evaluates what that worker was doing.

        Jobs held by no lease are reclaimed last (ADR 0096). The
        two services above start from a lease or from an offline
        node, and neither reaches a job whose lease row is already
        gone. Running this one after them means it only sees what
        they left behind.

        Each step runs even when an earlier one raised. A step that
        keeps failing must not stop the repairs after it, least of
        all the one that repairs what a failed step left behind.
        The failure is logged and the next pass tries again.
        """
        self._run(self._mark_dead_workers_service.execute)

        self._run(self._recover_expired_lease_service.execute)

        self._run(self._recover_offline_node_service.execute)

        self._run(self._recover_leaseless_job_service.execute)

    @staticmethod
    def _run(
        step: Callable[[], None],
    ) -> None:
        try:
            step()
        except Exception:
            logger.exception(
                "Reconciliation step %s failed. The remaining steps "
                "still run.",
                getattr(step, "__qualname__", repr(step)),
            )
