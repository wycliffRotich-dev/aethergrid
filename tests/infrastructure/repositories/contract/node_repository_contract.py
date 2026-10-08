from __future__ import annotations

import copy

import pytest

from app.domain.entities.node import Node
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.exceptions.node_tenant_conflict_error import (
    NodeTenantConflictError,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.tenant_id import TenantId
from tests.support.nodes import make_node


class NodeRepositoryContract:
    """
    Shared behavioral contract that every NodeRepository
    implementation must satisfy.

    Subclass this in a concrete test file and provide a
    `repository` fixture that returns a fresh, empty
    implementation under test. Every test defined here
    runs unchanged against both InMemoryNodeRepository and
    PostgresNodeRepository, proving the abstraction holds
    across persistence backends.
    """

    @pytest.fixture
    def repository(self):
        raise NotImplementedError("Subclasses must provide a `repository` fixture.")

    def _make_node(self, **overrides) -> Node:
        return make_node(**overrides)

    def test_save_and_get_by_id_round_trip(self, repository):
        node = self._make_node()

        repository.save(node)
        fetched = repository.get_by_id(node.id)

        assert fetched is not None
        assert fetched.id == node.id
        assert fetched.capacity == node.capacity
        assert fetched.available == node.available

    def test_get_by_id_returns_none_when_missing(self, repository):
        assert repository.get_by_id(NodeId.new()) is None

    def test_save_preserves_partial_allocation(self, repository):
        """
        Guards against the exact bug this contract suite was
        built to catch: a node with resources already
        allocated to running jobs must not silently reset to
        full capacity on reconstruction from storage.
        """
        node = self._make_node()
        node.allocate(
            ResourceRequirements(
                cpu_cores=3,
                memory_mib=4096,
                vram_mib=0,
            )
        )

        repository.save(node)
        fetched = repository.get_by_id(node.id)

        assert fetched.available.cpu_cores == 5
        assert fetched.available.memory_mib == 12288
        assert fetched.available.vram_mib == 8192

    def test_save_upserts_existing_node(self, repository):
        node = self._make_node()
        repository.save(node)

        node.drain()
        repository.save(node)

        fetched = repository.get_by_id(node.id)
        assert fetched.is_draining() is True

    def test_list_returns_all_saved_nodes(self, repository):
        node_a = self._make_node()
        node_b = self._make_node()

        repository.save(node_a)
        repository.save(node_b)

        ids = {n.id for n in repository.list()}
        assert ids == {node_a.id, node_b.id}

    def test_list_available_excludes_draining_nodes(self, repository):
        available_node = self._make_node()
        draining_node = self._make_node()
        draining_node.drain()

        repository.save(available_node)
        repository.save(draining_node)

        ids = {n.id for n in repository.list_available()}
        assert available_node.id in ids
        assert draining_node.id not in ids

    def test_delete_removes_node(self, repository):
        node = self._make_node()
        repository.save(node)

        repository.delete(node.id)

        assert repository.get_by_id(node.id) is None
        assert node.id not in {n.id for n in repository.list()}

    def test_labels_round_trip(self, repository):
        node = self._make_node(
            labels={"gpu": "a100", "zone": "nrb-1"},
        )

        repository.save(node)
        fetched = repository.get_by_id(node.id)

        assert fetched.labels == {"gpu": "a100", "zone": "nrb-1"}

    @pytest.fixture
    def second_tenant_id(self) -> TenantId:
        """
        A tenant other than the default one. Backends whose
        storage enforces tenant rows override this to create
        the tenant first.
        """
        return TenantId.new()

    def test_a_node_keeps_a_non_default_tenant(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        node = self._make_node(tenant_id=second_tenant_id)
        repository.save(node)

        fetched = repository.get_by_id(node.id)

        assert fetched is not None
        assert fetched.tenant_id == second_tenant_id

    def test_save_in_another_tenant_raises_and_changes_nothing(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        node = self._make_node()
        repository.save(node)

        # A separate object with the same id, claiming another
        # tenant and other values. Saving it is reported as a
        # conflict and must not move or change the stored node.
        impostor = copy.deepcopy(node)
        impostor.tenant_id = second_tenant_id
        impostor.name = "impostor"
        impostor.draining = True

        with pytest.raises(NodeTenantConflictError):
            repository.save(impostor)

        fetched = repository.get_by_id(node.id)

        assert fetched is not None
        assert fetched.tenant_id == DEFAULT_TENANT_ID
        assert fetched.name == node.name
        assert fetched.draining is False

    def test_across_tenants_reads_see_nodes_in_every_tenant(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        mine = self._make_node()
        theirs = self._make_node(tenant_id=second_tenant_id)
        repository.save(mine)
        repository.save(theirs)

        listed = repository.list_across_tenants()
        fetched = repository.get_by_id_across_tenants(theirs.id)

        assert {node.id for node in listed} == {mine.id, theirs.id}
        assert fetched is not None
        assert fetched.tenant_id == second_tenant_id
        assert repository.get_by_id_across_tenants(NodeId.new()) is None

    def test_list_available_across_tenants_skips_draining_nodes(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        ready = self._make_node(tenant_id=second_tenant_id)
        draining = self._make_node(draining=True)
        repository.save(ready)
        repository.save(draining)

        available = {
            node.id for node in repository.list_available_across_tenants()
        }

        assert ready.id in available
        assert draining.id not in available
