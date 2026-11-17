from __future__ import annotations

import copy
import threading
from datetime import timedelta

import pytest

from app.domain.entities.node import HEARTBEAT_TIMEOUT, Node, utc_now
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

    # A backend whose single connection is not safe for concurrent
    # writes overrides this to False, and the concurrent test skips.
    concurrent_safe = True

    @pytest.fixture
    def repository(self):
        raise NotImplementedError("Subclasses must provide a `repository` fixture.")

    def _make_node(self, **overrides) -> Node:
        return make_node(**overrides)

    def test_save_and_get_by_id_round_trip(self, repository):
        node = self._make_node()

        repository.save(node)
        fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)

        assert fetched is not None
        assert fetched.id == node.id
        assert fetched.capacity == node.capacity
        assert fetched.available == node.available

    def test_get_by_id_returns_none_when_missing(self, repository):
        assert repository.get_by_id(NodeId.new(), DEFAULT_TENANT_ID) is None

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
                vram_mib=1024,
            )
        )

        repository.save(node)
        fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)

        assert fetched.available.cpu_cores == 5
        assert fetched.available.memory_mib == 12288
        assert fetched.available.vram_mib == 7168

    def test_save_upserts_existing_node(self, repository):
        node = self._make_node()
        repository.save(node)

        node.drain()
        repository.save(node)

        fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)
        assert fetched.is_draining() is True

    def test_list_returns_all_saved_nodes(self, repository):
        node_a = self._make_node()
        node_b = self._make_node()

        repository.save(node_a)
        repository.save(node_b)

        ids = {n.id for n in repository.list(DEFAULT_TENANT_ID)}
        assert ids == {node_a.id, node_b.id}

    def test_delete_removes_node(self, repository):
        node = self._make_node()
        repository.save(node)

        repository.delete(node.id, DEFAULT_TENANT_ID)

        assert repository.get_by_id(node.id, DEFAULT_TENANT_ID) is None
        assert node.id not in {n.id for n in repository.list(DEFAULT_TENANT_ID)}

    def test_labels_round_trip(self, repository):
        node = self._make_node(
            labels={"gpu": "a100", "zone": "nrb-1"},
        )

        repository.save(node)
        fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)

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

        fetched = repository.get_by_id(node.id, second_tenant_id)

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

        fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)

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

    def test_list_available_across_tenants_skips_stale_nodes(
        self,
        repository,
    ) -> None:
        """
        "Available" means alive and not draining, on every backend.
        A node whose heartbeat is older than the liveness timeout
        must not be offered to the scheduler.
        """
        healthy = self._make_node()
        stale = self._make_node()
        stale.last_seen_at = stale.last_seen_at - HEARTBEAT_TIMEOUT * 2
        repository.save(healthy)
        repository.save(stale)

        available = {
            node.id for node in repository.list_available_across_tenants()
        }

        assert healthy.id in available
        assert stale.id not in available

    def test_get_by_id_in_another_tenant_returns_none(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        node = self._make_node()
        repository.save(node)

        assert repository.get_by_id(node.id, second_tenant_id) is None
        assert repository.get_by_id(node.id, DEFAULT_TENANT_ID) is not None

    def test_list_returns_only_the_callers_tenant(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        mine = self._make_node()
        theirs = self._make_node(tenant_id=second_tenant_id)
        repository.save(mine)
        repository.save(theirs)

        assert {n.id for n in repository.list(DEFAULT_TENANT_ID)} == {mine.id}
        assert {n.id for n in repository.list(second_tenant_id)} == {theirs.id}

    def test_delete_in_another_tenant_leaves_the_node(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        node = self._make_node()
        repository.save(node)

        repository.delete(node.id, second_tenant_id)

        assert repository.get_by_id(node.id, DEFAULT_TENANT_ID) is not None

    def test_record_heartbeat_changes_only_the_heartbeat_time(
        self,
        repository,
    ) -> None:
        """
        A heartbeat carries no capacity figures, so it must not
        touch any of them. The node holds a partial allocation, a
        label and a name, and all of them must come back as saved.
        """
        node = self._make_node(labels={"zone": "nrb-1"})
        node.allocate(
            ResourceRequirements(
                cpu_cores=3,
                memory_mib=4096,
                vram_mib=1024,
            )
        )
        saved_seen_at = node.last_seen_at
        seen_at = saved_seen_at + timedelta(minutes=10)
        repository.save(node)

        recorded = repository.record_heartbeat(
            node.id,
            DEFAULT_TENANT_ID,
            seen_at,
        )

        fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)

        assert recorded is True
        assert fetched is not None
        assert fetched.last_seen_at == seen_at
        assert fetched.available.cpu_cores == 5
        assert fetched.available.memory_mib == 12288
        assert fetched.available.vram_mib == 7168
        assert fetched.capacity == node.capacity
        assert fetched.labels == {"zone": "nrb-1"}
        assert fetched.name == node.name
        assert fetched.draining is False

    def test_record_heartbeat_for_a_missing_node_returns_false(
        self,
        repository,
    ) -> None:
        recorded = repository.record_heartbeat(
            NodeId.new(),
            DEFAULT_TENANT_ID,
            utc_now(),
        )

        assert recorded is False

    def test_record_heartbeat_in_another_tenant_returns_false(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        node = self._make_node()
        saved_seen_at = node.last_seen_at
        repository.save(node)

        recorded = repository.record_heartbeat(
            node.id,
            second_tenant_id,
            saved_seen_at + timedelta(minutes=10),
        )

        fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)

        assert recorded is False
        assert fetched is not None
        assert fetched.last_seen_at == saved_seen_at

    def test_record_heartbeat_makes_a_stale_node_available_again(
        self,
        repository,
    ) -> None:
        stale = self._make_node()
        stale.last_seen_at = stale.last_seen_at - HEARTBEAT_TIMEOUT * 2
        repository.save(stale)

        assert stale.id not in {
            node.id for node in repository.list_available_across_tenants()
        }

        recorded = repository.record_heartbeat(
            stale.id,
            DEFAULT_TENANT_ID,
            utc_now(),
        )

        assert recorded is True
        assert stale.id in {
            node.id for node in repository.list_available_across_tenants()
        }

    def test_allocate_reduces_available(self, repository):
        node = self._make_node()
        repository.save(node)

        allocated = repository.allocate(
            node.id,
            DEFAULT_TENANT_ID,
            ResourceRequirements(
                cpu_cores=3,
                memory_mib=4096,
                vram_mib=1024,
            ),
        )

        fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)

        assert allocated is True
        assert fetched is not None
        assert fetched.available.cpu_cores == 5
        assert fetched.available.memory_mib == 12288
        assert fetched.available.vram_mib == 7168

    def test_allocate_returns_false_when_capacity_is_insufficient(
        self,
        repository,
    ) -> None:
        # The fence that prevents over-commit: a request that no
        # longer fits the node's real, current available capacity is
        # refused and changes nothing (ADR 0105).
        node = self._make_node()
        repository.save(node)

        allocated = repository.allocate(
            node.id,
            DEFAULT_TENANT_ID,
            ResourceRequirements(
                cpu_cores=9,
                memory_mib=1,
                vram_mib=0,
            ),
        )

        fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)

        assert allocated is False
        assert fetched is not None
        assert fetched.available.cpu_cores == 8
        assert fetched.available.memory_mib == 16384

    def test_allocate_in_another_tenant_returns_false_and_changes_nothing(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        node = self._make_node()
        repository.save(node)

        allocated = repository.allocate(
            node.id,
            second_tenant_id,
            ResourceRequirements(
                cpu_cores=1,
                memory_mib=512,
                vram_mib=0,
            ),
        )

        fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)

        assert allocated is False
        assert fetched is not None
        assert fetched.available.cpu_cores == 8

    def test_allocate_for_a_missing_node_returns_false(
        self,
        repository,
    ) -> None:
        allocated = repository.allocate(
            NodeId.new(),
            DEFAULT_TENANT_ID,
            ResourceRequirements(
                cpu_cores=1,
                memory_mib=512,
                vram_mib=0,
            ),
        )

        assert allocated is False

    def test_release_returns_capacity_up_to_the_ceiling(
        self,
        repository,
    ) -> None:
        node = self._make_node()
        repository.save(node)
        repository.allocate(
            node.id,
            DEFAULT_TENANT_ID,
            ResourceRequirements(
                cpu_cores=3,
                memory_mib=4096,
                vram_mib=1024,
            ),
        )

        released = repository.release(
            node.id,
            DEFAULT_TENANT_ID,
            ResourceRequirements(
                cpu_cores=1,
                memory_mib=1024,
                vram_mib=512,
            ),
        )

        fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)

        assert released is True
        assert fetched is not None
        assert fetched.available.cpu_cores == 6
        assert fetched.available.memory_mib == 13312
        assert fetched.available.vram_mib == 7680

    def test_release_caps_available_at_capacity(
        self,
        repository,
    ) -> None:
        # Releasing more than was allocated, or releasing against a
        # full node, must never report more capacity than the node
        # has. The add is capped at the capacity ceiling (ADR 0105).
        node = self._make_node()
        repository.save(node)

        released = repository.release(
            node.id,
            DEFAULT_TENANT_ID,
            ResourceRequirements(
                cpu_cores=3,
                memory_mib=4096,
                vram_mib=1024,
            ),
        )

        fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)

        assert released is True
        assert fetched is not None
        assert fetched.available.cpu_cores == 8
        assert fetched.available.memory_mib == 16384
        assert fetched.available.vram_mib == 8192

    def test_release_in_another_tenant_returns_false_and_changes_nothing(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        node = self._make_node()
        repository.save(node)

        released = repository.release(
            node.id,
            second_tenant_id,
            ResourceRequirements(
                cpu_cores=1,
                memory_mib=512,
                vram_mib=0,
            ),
        )

        fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)

        assert released is False
        assert fetched is not None
        assert fetched.available.cpu_cores == 8

    def test_release_for_a_missing_node_returns_false(
        self,
        repository,
    ) -> None:
        released = repository.release(
            NodeId.new(),
            DEFAULT_TENANT_ID,
            ResourceRequirements(
                cpu_cores=1,
                memory_mib=512,
                vram_mib=0,
            ),
        )

        assert released is False

    def test_concurrent_allocate_never_over_commits(
        self,
        repository,
    ) -> None:
        # ADR 0105: allocate is one atomic operation. Threads racing to
        # allocate against a node with room for exactly K must produce
        # exactly K successful allocations, never more.
        if not self.concurrent_safe:
            pytest.skip("backend does not support concurrent writes")

        node = self._make_node(
            capacity=ResourceRequirements(
                cpu_cores=4,
                memory_mib=4096,
                vram_mib=0,
            ),
        )
        repository.save(node)

        threads = 8
        request = ResourceRequirements(
            cpu_cores=1,
            memory_mib=1024,
            vram_mib=0,
        )

        barrier = threading.Barrier(threads)
        results: list[bool] = [False] * threads

        def allocate_one(index: int) -> None:
            barrier.wait()
            results[index] = repository.allocate(
                node.id,
                DEFAULT_TENANT_ID,
                request,
            )

        workers = [
            threading.Thread(target=allocate_one, args=(index,))
            for index in range(threads)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        assert sum(results) == 4
        fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)
        assert fetched is not None
        assert fetched.available.cpu_cores == 0
        assert fetched.available.memory_mib == 0

    def test_allocate_and_release_agree_with_the_domain_rule(
        self,
        repository,
    ) -> None:
        # The capacity rule lives in Node (can_host, allocate, release)
        # and again as SQL in the repositories. Both must agree on exact
        # fit, one-short and release-over-capacity (ADR 0105).
        exact = ResourceRequirements(
            cpu_cores=8,
            memory_mib=16384,
            vram_mib=8192,
        )
        short_cpu = ResourceRequirements(
            cpu_cores=9,
            memory_mib=1,
            vram_mib=0,
        )
        short_mem = ResourceRequirements(
            cpu_cores=1,
            memory_mib=16385,
            vram_mib=0,
        )

        for request, expected in (
            (exact, True),
            (short_cpu, False),
            (short_mem, False),
        ):
            node = self._make_node()
            repository.save(node)

            allocated = repository.allocate(
                node.id,
                DEFAULT_TENANT_ID,
                request,
            )

            domain = self._make_node()
            if domain.can_host(request):
                domain.allocate(request)

            fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)

            assert allocated is expected
            assert fetched is not None
            assert fetched.available == domain.available

        # Release over capacity caps at capacity in both places.
        node = self._make_node()
        repository.save(node)
        over = ResourceRequirements(
            cpu_cores=1,
            memory_mib=1024,
            vram_mib=512,
        )

        released = repository.release(node.id, DEFAULT_TENANT_ID, over)
        domain = self._make_node()
        domain.release(over)
        fetched = repository.get_by_id(node.id, DEFAULT_TENANT_ID)

        assert released is True
        assert fetched is not None
        assert fetched.available == domain.available
