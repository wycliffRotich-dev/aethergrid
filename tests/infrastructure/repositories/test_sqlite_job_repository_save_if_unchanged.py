from __future__ import annotations

import copy
import sqlite3

import pytest

from app.domain.exceptions.job_tenant_conflict_error import (
    JobTenantConflictError,
)
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.tenant_id import TenantId
from app.infrastructure.repositories.sqlite_job_repository import (
    SqliteJobRepository,
)
from tests.infrastructure.repositories.contract.job_repository_save_if_unchanged_contract import (
    JobRepositorySaveIfUnchangedContract,
)
from tests.support.jobs import make_job


class TestSqliteJobRepositorySaveIfUnchanged(
    JobRepositorySaveIfUnchangedContract
):
    @pytest.fixture
    def repository(self) -> SqliteJobRepository:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        return SqliteJobRepository(conn)

    def test_refusal_releases_transaction_without_rolling_back_shared_connection_writes(
        self,
    ) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE sibling_writes (marker INTEGER)")
        conn.commit()
        repository = SqliteJobRepository(conn)

        job = make_job()
        job.queue()
        repository.save(job)

        stale_expected = copy.deepcopy(job)
        stale_expected.assign_to(NodeId.new())
        stale_expected.start()
        stale_cancel = copy.deepcopy(stale_expected)
        stale_cancel.request_cancellation()

        # Simulate an uncommitted write on the same shared connection
        # from a sibling SQLite repository before save_if_unchanged
        # misses its WHERE predicate.
        conn.execute(
            "INSERT INTO sibling_writes (marker) VALUES (?)",
            (42,),
        )
        assert conn.in_transaction is True

        assert (
            repository.save_if_unchanged(stale_cancel, stale_expected)
            is False
        )
        assert conn.in_transaction is False

        sibling_row = conn.execute(
            "SELECT marker FROM sibling_writes"
        ).fetchone()
        assert sibling_row is not None
        assert sibling_row["marker"] == 42

        expected_impostor = copy.deepcopy(job)
        expected_impostor.tenant_id = TenantId.new()
        impostor = copy.deepcopy(expected_impostor)
        impostor.cancel()
        with pytest.raises(JobTenantConflictError):
            repository.save_if_unchanged(impostor, expected_impostor)
        assert conn.in_transaction is False
