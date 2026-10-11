from __future__ import annotations

import pytest

from app.infrastructure.repositories.sqlite_connection import (
    create_connection,
)
from app.infrastructure.repositories.sqlite_node_repository import (
    SqliteNodeRepository,
)
from tests.infrastructure.repositories.contract.node_repository_contract import (
    NodeRepositoryContract,
)


class TestSqliteNodeRepositoryContract(NodeRepositoryContract):
    @pytest.fixture
    def repository(self, tmp_path):
        connection = create_connection(str(tmp_path / "nodes.db"))
        yield SqliteNodeRepository(connection)
        connection.close()
