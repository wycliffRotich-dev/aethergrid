"""In-memory repositories that behave like a database for one thing: a
read hands back a copy, and a write stores one.

The plain in-memory repositories return the object they store. A
change that was made to it and never saved is still visible through
the repository, which hides the failures that recovery code exists
for. These classes make an unsaved change invisible, as it is on
Postgres.
"""

from __future__ import annotations

import copy
from collections.abc import Callable

from app.domain.entities.job import Job
from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.enums.job_status import JobStatus
from app.domain.repositories.lease_repository import LeaseRepository
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.in_memory_job_repository import (
    InMemoryJobRepository,
)
from app.infrastructure.repositories.in_memory_node_repository import (
    InMemoryNodeRepository,
)
from app.infrastructure.repositories.in_memory_worker_repository import (
    InMemoryWorkerRepository,
)


class CopyingJobRepository(InMemoryJobRepository):
    """
    Copies on every read and write, and can lose a write or run a
    hook after a read, to put a competing writer at an exact point.
    """

    def __init__(
        self,
        jobs: list[Job],
        lease_repository: LeaseRepository,
    ) -> None:
        # Set before the parent saves the first jobs through save().
        self.fail_next_write = False
        self.fail_write_of: JobId | None = None
        self.after_read: Callable[[], None] | None = None
        self.writes: list[str] = []
        super().__init__(
            [copy.deepcopy(job) for job in jobs],
            lease_repository=lease_repository,
        )
        self.writes.clear()

    def _maybe_lose(self, job: Job) -> None:
        if self.fail_next_write:
            self.fail_next_write = False
            raise RuntimeError("the write was lost")

        if job.id == self.fail_write_of:
            self.fail_write_of = None
            raise RuntimeError("the write was lost")

    def save(self, job: Job) -> None:
        self._maybe_lose(job)
        self.writes.append("job")
        super().save(copy.deepcopy(job))

    def save_if_leaseless(
        self,
        job: Job,
        expected_status: JobStatus,
    ) -> bool:
        self._maybe_lose(job)
        saved = super().save_if_leaseless(
            copy.deepcopy(job),
            expected_status,
        )
        if saved:
            self.writes.append("job")
        return saved

    def get_by_id(
        self,
        job_id: JobId,
        tenant_id: TenantId,
    ) -> Job | None:
        found = copy.deepcopy(super().get_by_id(job_id, tenant_id))

        if self.after_read is not None:
            hook, self.after_read = self.after_read, None
            hook()

        return found

    def list_across_tenants(self) -> list[Job]:
        return [copy.deepcopy(job) for job in super().list_across_tenants()]


class CopyingNodeRepository(InMemoryNodeRepository):
    def __init__(self, nodes: list[Node]) -> None:
        self.writes: list[str] = []
        super().__init__([copy.deepcopy(node) for node in nodes])
        self.writes.clear()

    def save(self, node: Node) -> None:
        self.writes.append("node")
        super().save(copy.deepcopy(node))

    def get_by_id(self, node_id, tenant_id):  # type: ignore[no-untyped-def]
        return copy.deepcopy(super().get_by_id(node_id, tenant_id))

    def list_across_tenants(self) -> list[Node]:
        return [copy.deepcopy(node) for node in super().list_across_tenants()]


class CopyingWorkerRepository(InMemoryWorkerRepository):
    def __init__(self, workers: list[Worker]) -> None:
        super().__init__([copy.deepcopy(worker) for worker in workers])

    def save(self, worker: Worker) -> None:
        super().save(copy.deepcopy(worker))

    def get_by_id(self, worker_id, tenant_id):  # type: ignore[no-untyped-def]
        return copy.deepcopy(super().get_by_id(worker_id, tenant_id))

    def list_across_tenants(self) -> list[Worker]:
        return [
            copy.deepcopy(worker) for worker in super().list_across_tenants()
        ]
