from __future__ import annotations

import pytest

from app.domain.entities.node import Node
from app.domain.entities.worker import Worker
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.worker_id import WorkerId


class WorkerRepositoryContract:
    """
    Shared behavioral contract that every WorkerRepository
    implementation must satisfy.

    Subclass this in a concrete test file and provide a
    `repository` fixture that returns a fresh, empty
    implementation under test.
    """

    @pytest.fixture
    def repository(self):
        raise NotImplementedError(
            "Subclasses must provide a `repository` fixture."
        )

    def _make_worker(self) -> Worker:
        node = Node(
            id=NodeId.new(),
            capacity=ResourceRequirements(
                cpu_cores=8,
                memory_mib=16_000,
                vram_mib=0,
            ),
        )

        return Worker(
            id=WorkerId.new(),
            node=node,
        )

    def test_save_and_get_by_id(
        self,
        repository,
    ) -> None:
        worker = self._make_worker()

        repository.save(worker)

        stored = repository.get_by_id(worker.id)

        assert stored is not None
        assert stored.id == worker.id

    def test_get_by_id_returns_none_when_missing(
        self,
        repository,
    ) -> None:
        assert repository.get_by_id(WorkerId.new()) is None

    def test_get_by_node_id_returns_matching_worker(
        self,
        repository,
    ) -> None:
        worker = self._make_worker()
        repository.save(worker)

        stored = repository.get_by_node_id(worker.node.id)

        assert stored is not None
        assert stored.id == worker.id

    def test_get_by_node_id_returns_none_when_missing(
        self,
        repository,
    ) -> None:
        assert repository.get_by_node_id(NodeId.new()) is None

    def test_list_workers(
        self,
        repository,
    ) -> None:
        worker = self._make_worker()

        repository.save(worker)

        workers = repository.list()

        ids = {w.id for w in workers}
        assert worker.id in ids
        assert len(workers) == 1

    def test_remove_worker(
        self,
        repository,
    ) -> None:
        worker = self._make_worker()

        repository.save(worker)

        repository.delete(worker.id)

        assert repository.get_by_id(worker.id) is None
