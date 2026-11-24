from __future__ import annotations

from enum import StrEnum


class LeaseRecoveryPath(StrEnum):
    """
    Which recovery path deleted a lease while it reclaimed a job
    (ADR 0107, decision 1). The values are the ones the check
    constraint of migration 0008 accepts, so a change here needs a
    migration.
    """

    EXPIRED_LEASE = "expired_lease"
    OFFLINE_NODE = "offline_node"
    WORKER_REGISTERED = "worker_registered"
