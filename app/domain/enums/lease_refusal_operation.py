from __future__ import annotations

from enum import StrEnum


class LeaseRefusalOperation(StrEnum):
    """
    Which call was refused because the lease it named is no longer the
    lease of its worker (ADR 0108, decision 1). The values are the ones
    the check constraint of migration 0009 accepts, so a change here
    needs a migration. An outcome report is refused through the release,
    so it is recorded as RELEASE.
    """

    RENEW = "renew"
    RELEASE = "release"
