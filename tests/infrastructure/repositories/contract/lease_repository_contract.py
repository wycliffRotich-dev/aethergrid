from __future__ import annotations

from datetime import timedelta

import pytest

from app.domain.entities.lease import DEFAULT_LEASE_DURATION, Lease
from app.domain.entities.worker import Worker
from app.domain.exceptions.lease_not_found_error import LeaseNotFoundError
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.resource_requirements import (
    ResourceRequirements,
)
from app.domain.value_objects.worker_id import WorkerId
from tests.support.jobs import make_job
from tests.support.nodes import make_node


class LeaseRepositoryContract:
    """
    Shared behavioral contract that every
    LeaseRepository implementation must satisfy.
    """

    @pytest.fixture
    def repository(self):
        raise NotImplementedError(
            "Subclasses must provide a `repository` fixture."
        )

    def _make_lease(
        self,
        *,
        duration: timedelta = DEFAULT_LEASE_DURATION,
    ) -> Lease:
        node = make_node(
            id=NodeId.new(),
            capacity=ResourceRequirements(
                cpu_cores=8,
                memory_mib=16384,
                vram_mib=8192,
            ),
        )

        worker = Worker(
            id=WorkerId.new(),
            node=node,
        )

        job = make_job(
            id=JobId.new(),
            resources=ResourceRequirements(
                cpu_cores=1,
                memory_mib=512,
                vram_mib=0,
            ),
        )

        return Lease.create(
            worker_id=worker.id,
            job_id=job.id,
            duration=duration,
        )

    def test_save_and_get_by_job_id(
        self,
        repository,
    ) -> None:
        lease = self._make_lease()

        repository.save(lease)

        fetched = repository.get_by_job_id(
            lease.job_id,
        )

        assert fetched is not None
        assert fetched.id == lease.id
        assert fetched.job_id == lease.job_id
        assert fetched.worker_id == lease.worker_id

    def test_save_and_get_by_worker_id(
        self,
        repository,
    ) -> None:
        lease = self._make_lease()

        repository.save(lease)

        fetched = repository.get_by_worker_id(
            lease.worker_id,
        )

        assert fetched is not None
        assert fetched.id == lease.id

    def test_list_returns_all_leases(
        self,
        repository,
    ) -> None:
        lease1 = self._make_lease()
        lease2 = self._make_lease()

        repository.save(lease1)
        repository.save(lease2)

        ids = {
            lease.id
            for lease in repository.list()
        }

        assert ids == {
            lease1.id,
            lease2.id,
        }

    def test_delete_removes_lease(
        self,
        repository,
    ) -> None:
        lease = self._make_lease()

        repository.save(lease)

        repository.delete(
            lease.job_id,
        )

        assert (
            repository.get_by_job_id(
                lease.job_id,
            )
            is None
        )

    def test_delete_if_expired_removes_an_expired_lease(
        self,
        repository,
    ) -> None:
        lease = self._make_lease(
            duration=timedelta(seconds=-1),
        )

        repository.save(lease)

        deleted = repository.delete_if_expired(
            lease.job_id,
        )

        assert deleted is True
        assert (
            repository.get_by_job_id(
                lease.job_id,
            )
            is None
        )

    def test_delete_if_expired_leaves_a_non_expired_lease_untouched(
        self,
        repository,
    ) -> None:
        # The actual race this method exists to close: a worker's
        # background renewal thread extends a lease's expiry between
        # reconciliation reading a stale, already-expired snapshot
        # and reconciliation's own delete call. delete_if_expired()
        # re-checks expiry atomically at delete time, so a lease that
        # is no longer expired by the time this runs must survive,
        # even though the caller believed it was expired when it
        # decided to call this.
        lease = self._make_lease(
            duration=timedelta(seconds=-1),
        )

        repository.save(lease)

        repository.renew(
            lease.id,
            DEFAULT_LEASE_DURATION,
        )

        deleted = repository.delete_if_expired(
            lease.job_id,
        )

        assert deleted is False
        assert (
            repository.get_by_job_id(
                lease.job_id,
            )
            is not None
        )

    def test_delete_if_expired_returns_false_when_no_lease_exists(
        self,
        repository,
    ) -> None:
        # deliberately never saved
        lease = self._make_lease()

        deleted = repository.delete_if_expired(
            lease.job_id,
        )

        assert deleted is False

        assert (
            repository.get_by_worker_id(
                lease.worker_id,
            )
            is None
        )

    def test_renew_extends_expiry_of_an_existing_lease(
        self,
        repository,
    ) -> None:
        lease = self._make_lease()

        repository.save(lease)

        original_expiry = lease.expires_at

        repository.renew(
            lease.id,
            DEFAULT_LEASE_DURATION,
        )

        renewed = repository.get_by_job_id(
            lease.job_id,
        )

        assert renewed is not None
        assert renewed.expires_at > original_expiry

    def test_renew_raises_when_lease_does_not_exist(
        self,
        repository,
    ) -> None:
        # deliberately never saved -- this is the reconciliation-
        # already-reclaimed-it case, and it must not silently create
        # a lease that looks like it was always there
        lease = self._make_lease()

        with pytest.raises(LeaseNotFoundError):
            repository.renew(
                lease.id,
                DEFAULT_LEASE_DURATION,
            )

    def test_renew_does_not_resurrect_a_deleted_lease(
        self,
        repository,
    ) -> None:
        # the actual bug this whole contract addition exists to
        # prevent: a renewal racing a delete must not recreate the row
        lease = self._make_lease()

        repository.save(lease)
        repository.delete(lease.job_id)

        with pytest.raises(LeaseNotFoundError):
            repository.renew(
                lease.id,
                DEFAULT_LEASE_DURATION,
            )

        assert (
            repository.get_by_job_id(
                lease.job_id,
            )
            is None
        )
