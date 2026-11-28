from __future__ import annotations

import copy

import pytest

from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.enums.job_status import JobStatus
from app.domain.exceptions.job_tenant_conflict_error import (
    JobTenantConflictError,
)
from app.domain.value_objects.job_id import JobId
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.tenant_id import TenantId
from tests.support.jobs import make_job


class JobRepositorySaveIfUnchangedContract:
    """
    The lifecycle-state-fenced write contract every JobRepository
    must satisfy (ADR 0106).
    """

    @pytest.fixture
    def repository(self):
        raise NotImplementedError(
            "Subclasses must provide a `repository` fixture."
        )

    @pytest.fixture
    def node_id(self) -> NodeId:
        return NodeId.new()

    @pytest.fixture
    def second_node_id(self) -> NodeId:
        return NodeId.new()

    @pytest.fixture
    def second_tenant_id(self) -> TenantId:
        return TenantId.new()

    def test_updates_when_stored_lifecycle_matches_expected(
        self,
        repository,
    ) -> None:
        job = make_job()
        job.queue()
        repository.save(job)

        expected = copy.deepcopy(job)
        updated = copy.deepcopy(expected)
        updated.cancel()
        wrote = repository.save_if_unchanged(updated, expected)

        assert wrote is True
        fetched = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
        assert fetched is not None
        assert fetched.status == JobStatus.CANCELLED

    def test_refuses_and_leaves_row_untouched_when_status_changed(
        self,
        repository,
        node_id: NodeId,
    ) -> None:
        job = make_job()
        job.queue()
        job.assign_to(node_id)
        job.start()
        repository.save(job)

        expected = copy.deepcopy(job)
        stale_cancel = copy.deepcopy(expected)
        stale_cancel.request_cancellation()

        settled = copy.deepcopy(job)
        settled.complete(exit_code=0)
        repository.save(settled)

        wrote = repository.save_if_unchanged(stale_cancel, expected)

        assert wrote is False
        fetched = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
        assert fetched is not None
        assert fetched.status == JobStatus.COMPLETED
        assert fetched.cancellation_requested_at is None
        assert fetched.exit_code == 0

    def test_refuses_stale_running_snapshot_after_retry_reenters_running(
        self,
        repository,
        node_id: NodeId,
        second_node_id: NodeId,
    ) -> None:
        job = make_job(max_retries=2)
        job.queue()
        job.assign_to(node_id)
        job.start()
        repository.save(job)

        expected_attempt_zero = copy.deepcopy(job)
        stale_cancel = copy.deepcopy(expected_attempt_zero)
        stale_cancel.request_cancellation()

        retried = copy.deepcopy(job)
        retried.fail(exit_code=1)
        retried.retry()
        retried.assign_to(second_node_id)
        retried.start()
        repository.save(retried)

        wrote = repository.save_if_unchanged(
            stale_cancel,
            expected_attempt_zero,
        )

        assert wrote is False
        fetched = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
        assert fetched is not None
        assert fetched.status == JobStatus.RUNNING
        assert fetched.retry_count == 1
        assert fetched.assigned_node_id == second_node_id
        assert fetched.cancellation_requested_at is None

    def test_returns_false_when_job_is_missing(
        self,
        repository,
    ) -> None:
        missing = make_job()
        missing.queue()
        expected = copy.deepcopy(missing)
        missing.cancel()

        assert (
            repository.save_if_unchanged(missing, expected) is False
        )
        assert (
            repository.get_by_id(missing.id, DEFAULT_TENANT_ID)
            is None
        )

    def test_raises_value_error_when_expected_has_different_identity(
        self,
        repository,
    ) -> None:
        job = make_job()
        job.queue()
        expected_other_id = make_job(id=JobId.new())
        expected_other_id.queue()

        updated = copy.deepcopy(job)
        updated.cancel()

        with pytest.raises(ValueError):
            repository.save_if_unchanged(updated, expected_other_id)

        expected_other_tenant = copy.deepcopy(job)
        expected_other_tenant.tenant_id = TenantId.new()

        with pytest.raises(ValueError):
            repository.save_if_unchanged(
                updated,
                expected_other_tenant,
            )

    def test_raises_tenant_conflict_when_id_belongs_to_another_tenant(
        self,
        repository,
        second_tenant_id: TenantId,
    ) -> None:
        job = make_job(priority=2)
        job.queue()
        repository.save(job)

        expected_impostor = copy.deepcopy(job)
        expected_impostor.tenant_id = second_tenant_id
        impostor = copy.deepcopy(expected_impostor)
        impostor.cancel()

        with pytest.raises(JobTenantConflictError):
            repository.save_if_unchanged(impostor, expected_impostor)

        fetched = repository.get_by_id(job.id, DEFAULT_TENANT_ID)
        assert fetched is not None
        assert fetched.status == JobStatus.QUEUED
        assert fetched.priority == 2
