from __future__ import annotations

from enum import StrEnum


class LeaseRefusalReason(StrEnum):
    """
    Why a renew or a release was refused (ADR 0108, decision 1). The
    values are the ones the check constraint of migration 0009
    accepts, so a change here needs a migration.

    NO_ACTIVE_LEASE: the worker holds no lease, which is what a stale
    worker finds after reclaim removed its lease.
    LEASE_NOT_CURRENT: the worker holds another lease than the one the
    call named.
    """

    NO_ACTIVE_LEASE = "no_active_lease"
    LEASE_NOT_CURRENT = "lease_not_current"
