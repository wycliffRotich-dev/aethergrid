from __future__ import annotations

from abc import ABC, abstractmethod


class SchedulerLeadership(ABC):
    """
    Decides which process may run the cluster tick (ADR 0078).

    The tick schedules jobs, assigns workers and reconciles state
    left behind by dead workers. Two processes doing that at once
    can both read a node as having room and both allocate against
    it, so only the process that holds leadership runs a tick.

    Leadership narrows that window to a failover. It does not
    close it: a leader that stalls past the loss of its lock can
    finish a tick another process has already started. The unique
    constraints and the tenant checks stay as the backstop.
    """

    @abstractmethod
    def try_acquire(self) -> bool:
        """
        Return True when this process may run a tick now.

        Called once per tick, and safe to call again while this
        process already leads. Never raises for a lost lock or an
        unreachable database: both report False, so the caller
        skips the tick and asks again on the next one.
        """

    @abstractmethod
    def release(self) -> None:
        """
        Give up leadership, if this process holds it.

        Safe to call when it does not, and safe to call twice.
        """
