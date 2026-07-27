from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.domain.exceptions.insufficient_node_capacity_error import (
    InsufficientNodeCapacityError,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


HEARTBEAT_TIMEOUT = timedelta(minutes=1)

_NAME_ADJECTIVES = (
    "swift", "quiet", "bold", "steady", "bright", "calm",
    "sharp", "brisk", "keen", "solid", "clever", "eager",
    "loyal", "quick", "sturdy", "vivid", "wise", "agile",
    "gentle", "fierce",
)

_NAME_NOUNS = (
    "falcon", "otter", "badger", "heron", "lynx", "wren",
    "marten", "kestrel", "osprey", "raven", "sparrow", "vole",
    "ferret", "grouse", "harrier", "plover", "shrike", "stoat",
    "tern", "weasel",
)


def generate_node_name() -> str:
    """
    Produce a human-friendly display name for a node that
    was not given one explicitly, adjective-noun plus a
    short hex suffix for uniqueness, e.g. "swift-falcon-3f2a".

    This is a fallback, not the primary path: a real node
    agent registering itself is expected to supply its own
    hostname as the name. This generator only covers nodes
    registered without one, such as through the dashboard's
    manual registration form during testing.
    """
    adjective = random.choice(_NAME_ADJECTIVES)
    noun = random.choice(_NAME_NOUNS)
    suffix = f"{random.randint(0, 0xFFFF):04x}"

    return f"{adjective}-{noun}-{suffix}"


@dataclass(slots=True)
class Node:
    """
    Represents a compute node capable of executing jobs.
    """

    id: NodeId
    capacity: ResourceRequirements
    name: str = field(
        default_factory=generate_node_name,
    )
    labels: dict[str, str] = field(
        default_factory=dict,
    )
    last_seen_at: datetime = field(
        default_factory=utc_now,
    )
    draining: bool = False
    available: ResourceRequirements | None = None

    def __post_init__(self) -> None:
        """
        Default `available` to full capacity only when it
        was not explicitly provided. This lets a brand-new
        node start fully free (available == capacity) while
        still allowing a repository to reconstruct a node
        from storage with its true, partially-allocated
        available capacity intact.
        """
        if self.available is None:
            self.available = self.capacity

    def heartbeat(self) -> None:
        """
        Record that this node is alive.
        """
        self.last_seen_at = utc_now()

    def is_alive(self) -> bool:
        """
        Return True if the node has sent a heartbeat
        within the configured timeout.
        """
        return (utc_now() - self.last_seen_at) <= HEARTBEAT_TIMEOUT

    def drain(self) -> None:
        """
        Mark this node as draining.
        Draining nodes continue running existing
        workloads but must not receive newly
        scheduled jobs.
        """
        self.draining = True

    def is_draining(self) -> bool:
        """
        Return True if the node is currently
        draining.
        """
        return self.draining

    def can_host(
        self,
        requirements: ResourceRequirements,
    ) -> bool:
        """
        Return True if this node has sufficient
        available resources.
        """
        return (
            self.available.cpu_cores >= requirements.cpu_cores
            and self.available.memory_mib >= requirements.memory_mib
            and self.available.vram_mib >= requirements.vram_mib
        )

    def allocate(
        self,
        requirements: ResourceRequirements,
    ) -> None:
        """
        Allocate resources for a scheduled job.
        """
        if not self.can_host(
            requirements,
        ):
            raise InsufficientNodeCapacityError(
                f"Node {self.id} does not have enough available "
                "resources to satisfy the requested allocation."
            )
        self.available = ResourceRequirements(
            cpu_cores=(self.available.cpu_cores - requirements.cpu_cores),
            memory_mib=(self.available.memory_mib - requirements.memory_mib),
            vram_mib=(self.available.vram_mib - requirements.vram_mib),
        )

    def release(
        self,
        requirements: ResourceRequirements,
    ) -> None:
        """
        Release previously allocated resources
        back to the node.
        """
        self.available = ResourceRequirements(
            cpu_cores=min(
                self.available.cpu_cores + requirements.cpu_cores,
                self.capacity.cpu_cores,
            ),
            memory_mib=min(
                self.available.memory_mib + requirements.memory_mib,
                self.capacity.memory_mib,
            ),
            vram_mib=min(
                self.available.vram_mib + requirements.vram_mib,
                self.capacity.vram_mib,
            ),
        )
