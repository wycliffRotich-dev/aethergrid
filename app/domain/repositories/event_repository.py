from __future__ import annotations

import builtins
from abc import ABC, abstractmethod

from app.domain.entities.event import Event
from app.domain.value_objects.tenant_id import TenantId


class EventRepository(ABC):
    """
    Repository abstraction for domain events.
    """

    @abstractmethod
    def save(
        self,
        event: Event,
    ) -> None:
        """
        Persist a domain event.
        """

    @abstractmethod
    def list(
        self,
        tenant_id: TenantId,
    ) -> list[Event]:
        """
        Return the events of this tenant. An event of another tenant
        is not returned, and neither is one with no tenant
        (ADR 0074 decisions 4 and 7).
        """

    @abstractmethod
    def list_by_aggregate(
        self,
        aggregate_id: str,
        tenant_id: TenantId,
    ) -> builtins.list[Event]:
        """
        Return the events of an aggregate in this tenant. The same
        empty answer covers an aggregate that does not exist and one
        in another tenant (ADR 0064 point 5).
        """
