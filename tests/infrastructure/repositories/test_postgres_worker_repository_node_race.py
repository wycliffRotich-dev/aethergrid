from __future__ import annotations

import contextlib

import pytest

from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.value_objects.node_id import NodeId
from app.domain.value_objects.worker_id import WorkerId
from app.infrastructure.repositories.postgres_worker_repository import (
    PostgresWorkerRepository,
)


class _ScriptedConnection:
    """
    A connection that answers each read from a script, so a test can
    say what the worker read and the node read return, in order.
    """

    def __init__(self, fetchone_results=(), fetchall_rows=()):
        self._one = list(fetchone_results)
        self._all = list(fetchall_rows)

    def cursor(self, row_factory=None):
        return self

    def execute(self, query, params=None):
        return self

    def fetchone(self):
        return self._one.pop(0)

    def fetchall(self):
        return self._all


class _Pool:
    def __init__(self, connection):
        self._connection = connection

    def connection(self):
        return contextlib.nullcontext(self._connection)


def _worker_row() -> dict:
    return {"node_id": NodeId.new()}


@pytest.mark.parametrize(
    "lookup",
    [
        lambda repo: repo.get_by_id(WorkerId.new(), DEFAULT_TENANT_ID),
        lambda repo: repo.get_by_id_across_tenants(WorkerId.new()),
        lambda repo: repo.get_by_node_id(NodeId.new(), DEFAULT_TENANT_ID),
    ],
    ids=["get_by_id", "get_by_id_across_tenants", "get_by_node_id"],
)
def test_a_worker_whose_node_was_deleted_between_the_reads_is_not_found(
    lookup,
) -> None:
    connection = _ScriptedConnection(fetchone_results=[_worker_row(), None])
    repository = PostgresWorkerRepository(_Pool(connection))

    assert lookup(repository) is None


@pytest.mark.parametrize(
    "listing",
    [
        lambda repo: repo.list(DEFAULT_TENANT_ID),
        lambda repo: repo.list_across_tenants(),
    ],
    ids=["list", "list_across_tenants"],
)
def test_a_list_skips_workers_whose_node_was_deleted(listing) -> None:
    connection = _ScriptedConnection(
        fetchone_results=[None, None],
        fetchall_rows=[_worker_row(), _worker_row()],
    )
    repository = PostgresWorkerRepository(_Pool(connection))

    assert listing(repository) == []
