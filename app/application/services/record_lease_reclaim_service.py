from __future__ import annotations

import logging

from app.domain.entities.lease import Lease
from app.domain.entities.lease_reclaim import LeaseReclaim
from app.domain.enums.lease_recovery_path import LeaseRecoveryPath
from app.domain.repositories.lease_reclaim_repository import (
    LeaseReclaimRepository,
)

logger = logging.getLogger(__name__)


class RecordLeaseReclaimService:
    """
    Application service that keeps the record of a lease a recovery path
    deleted while it reclaimed a job (ADR 0107, decision 4).

    A failed save is logged as one warning and is not raised, so a failed
    write cannot stop a recovery pass or undo a reclaim.
    """

    def __init__(
        self,
        lease_reclaim_repository: LeaseReclaimRepository,
    ) -> None:
        self._lease_reclaim_repository = lease_reclaim_repository

    def record(
        self,
        lease: Lease,
        recovered_by: LeaseRecoveryPath,
    ) -> None:
        """
        Build the record of this deleted lease and save it.
        """
        record = LeaseReclaim.record(
            lease=lease,
            recovered_by=recovered_by,
        )

        try:
            self._lease_reclaim_repository.save(record)
        except Exception as error:
            logger.warning(
                "The record of reclaimed lease %s for job %s was not saved: %s",
                lease.id,
                lease.job_id,
                error,
            )
