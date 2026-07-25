from __future__ import annotations

from app.domain.exceptions.domain_error import DomainError


class InsufficientNodeCapacityError(DomainError):
    """
    Raised when an allocation is attempted against a specific node
    that does not have enough available resources to satisfy it.

    This differs from NoAvailableNodeError, which signals that no
    node in the cluster was eligible during scheduling. This error
    indicates a specific, already-selected node failed its own
    capacity invariant at allocation time -- expected to be rare,
    and typically a sign of a race condition or stale scheduling
    decision rather than routine cluster capacity exhaustion.
    """
