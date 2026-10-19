from __future__ import annotations


class LeaseTenantMismatchError(ValueError):
    """
    Raised when a lease would join a worker and a job that belong to
    different tenants (ADR 0075).

    It subclasses ValueError, as the other refusal of
    AcquireLeaseService does, so a caller that already handles that
    one keeps handling this one.
    """
