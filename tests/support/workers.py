from __future__ import annotations

from typing import Any

from app.domain.entities.worker import Worker
from app.domain.value_objects.worker_id import WorkerId
from tests.support.nodes import make_node


def make_worker(**overrides: Any) -> Worker:
    """
    Build a Worker for a test.

    Every test worker goes through here, so what a test worker looks
    like by default is decided in one place. Only the fields Worker
    requires are defaulted: a new id and a node built by make_node.
    Everything else, such as status and managed_by, keeps Worker's own
    default, so a test that does not name a field gets exactly what
    production code would. Any Worker field can be overridden by
    keyword.
    """
    defaults: dict[str, Any] = {
        "id": WorkerId.new(),
        "node": make_node(),
    }
    defaults.update(overrides)

    return Worker(**defaults)
