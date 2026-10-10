from __future__ import annotations

import copy

import pytest

from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.exceptions.job_tenant_conflict_error import (
    JobTenantConflictError,
)
from app.domain.value_objects.tenant_id import TenantId
from tests.support.jobs import make_job


class JobRepositoryTenantContract:
    """
    The tenant rules every JobRepository must follow (ADR 0064).

    Subclass this in a concrete test file and provide a `repository`
    fixture that returns a fresh, empty implementation under test.
    Backends whose storage enforces tenant rows also override
    `second_tenant_id` to create the tenant first.
    """

    @pytest.fixture
    def repository(self):
        raise NotImplementedError("Subclasses must provide a `repository` fixture.")

    @pytest.fixture
    def second_tenant_id(self) -> TenantId:
        return TenantId.new()

    def test_a_job_keeps_a_non_default_tenant(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        job = make_job(tenant_id=second_tenant_id)
        repository.save(job)

        fetched = repository.get_by_id(job.id, second_tenant_id)

        assert fetched is not None
        assert fetched.tenant_id == second_tenant_id

    def test_save_in_another_tenant_raises_and_changes_nothing(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        job = make_job(priority=1)
        repository.save(job)

        # A separate object with the same id, claiming another tenant
        # and other values. Saving it is reported as a conflict and
        # must not move or change the stored job.
        impostor = copy.deepcopy(job)
        impostor.tenant_id = second_tenant_id
        impostor.priority = 9

        with pytest.raises(JobTenantConflictError):
            repository.save(impostor)

        fetched = repository.get_by_id(job.id, DEFAULT_TENANT_ID)

        assert fetched is not None
        assert fetched.tenant_id == DEFAULT_TENANT_ID
        assert fetched.priority == 1

    def test_across_tenants_reads_see_jobs_in_every_tenant(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        mine = make_job()
        theirs = make_job(tenant_id=second_tenant_id)
        repository.save(mine)
        repository.save(theirs)

        listed = repository.list_across_tenants()
        fetched = repository.get_by_id_across_tenants(theirs.id)

        assert {job.id for job in listed} == {mine.id, theirs.id}
        assert fetched is not None
        assert fetched.tenant_id == second_tenant_id
        assert repository.get_by_id_across_tenants(make_job().id) is None

    def test_get_by_id_in_another_tenant_returns_none(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        job = make_job()
        repository.save(job)

        assert repository.get_by_id(job.id, second_tenant_id) is None
        assert repository.get_by_id(job.id, DEFAULT_TENANT_ID) is not None

    def test_list_recent_returns_only_the_callers_tenant(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        mine = make_job()
        theirs = make_job(tenant_id=second_tenant_id)
        repository.save(mine)
        repository.save(theirs)

        in_default = repository.list_recent(10, DEFAULT_TENANT_ID)
        in_second = repository.list_recent(10, second_tenant_id)

        assert [job.id for job in in_default] == [mine.id]
        assert [job.id for job in in_second] == [theirs.id]

    def test_list_queued_returns_only_the_callers_tenant(
        self,
        repository,
        second_tenant_id,
    ) -> None:
        mine = make_job()
        theirs = make_job(tenant_id=second_tenant_id)
        mine.queue()
        theirs.queue()
        repository.save(mine)
        repository.save(theirs)

        in_default = repository.list_queued(DEFAULT_TENANT_ID)
        in_second = repository.list_queued(second_tenant_id)

        assert [job.id for job in in_default] == [mine.id]
        assert [job.id for job in in_second] == [theirs.id]
