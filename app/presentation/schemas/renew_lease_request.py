from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class RenewLeaseRequest(BaseModel):
    """
    Request body for lease renewal.

    lease_id (ADR 0038) is the identity of the lease the
    caller believes it currently holds, echoed back from
    RunningJobResponse.lease_id (ADR 0036). It is required,
    not optional: without it, the service has no way to
    distinguish a genuinely current renewal from a stale one
    renewing a lease that was reclaimed and reassigned to a
    different job in the meantime, the same gap ADR 0034
    closed for release and ADR 0036 closed for outcome
    reporting.
    """

    lease_id: UUID
