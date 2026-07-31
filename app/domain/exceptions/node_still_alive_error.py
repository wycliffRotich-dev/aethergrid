from __future__ import annotations

from app.domain.exceptions.domain_error import DomainError


class NodeStillAliveError(DomainError):
    """
    Raised when an operation requires a node to be offline,
    and it isn't. Removing a node that's still sending
    heartbeats has to go through draining it first, not a
    direct delete -- this distinguishes that conflict from
    the node simply not existing at all.
    """

    pass
