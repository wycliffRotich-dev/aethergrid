from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from app.domain.enums.worker_management import WorkerManagement
from app.presentation.schemas.create_job_request import CreateJobRequest
from app.presentation.schemas.create_node_request import CreateNodeRequest
from app.presentation.schemas.create_worker_request import (
    CreateWorkerRequest,
)
from scripts.upgrade_rehearsal import (
    JOB_PAYLOAD,
    NODE_PAYLOAD,
    SeedIds,
    seed_cluster,
)


class FakeApi:
    def __init__(self, statuses: Mapping[str, int] | None = None) -> None:
        self.calls: list[tuple[str, Mapping[str, object]]] = []
        self._statuses = statuses or {}

    def post(
        self,
        path: str,
        payload: Mapping[str, object],
    ) -> tuple[int, str]:
        self.calls.append((path, payload))
        status = self._statuses.get(path, 201)
        return status, json.dumps({"id": f"{path.strip('/')}-id"})


def test_the_cluster_is_seeded_in_order_and_the_ids_are_returned() -> None:
    api = FakeApi()

    ids = seed_cluster(api.post)

    assert ids == SeedIds(node="nodes-id", worker="workers-id", job="jobs-id")
    assert [path for path, _ in api.calls] == ["/nodes", "/workers", "/jobs"]


def test_the_worker_is_registered_on_the_node_just_created() -> None:
    api = FakeApi()

    seed_cluster(api.post)

    assert api.calls[1][1]["node_id"] == "nodes-id"


def test_the_worker_is_managed_by_an_agent_so_nothing_runs_the_job() -> None:
    api = FakeApi()

    seed_cluster(api.post)

    assert api.calls[1][1]["managed_by"] == WorkerManagement.AGENT.value


def test_the_job_has_no_command() -> None:
    api = FakeApi()

    seed_cluster(api.post)

    assert "command" not in JOB_PAYLOAD
    assert "command" not in api.calls[2][1]


def test_the_payloads_are_valid_for_the_request_models_of_the_app() -> None:
    api = FakeApi()

    seed_cluster(api.post)

    CreateNodeRequest.model_validate(NODE_PAYLOAD)
    CreateWorkerRequest.model_validate(api.calls[1][1])
    CreateJobRequest.model_validate(JOB_PAYLOAD)


def test_a_refused_request_stops_the_seed_and_names_the_path_and_status() -> None:
    api = FakeApi({"/workers": 422})

    with pytest.raises(ValueError, match="POST /workers returned 422"):
        seed_cluster(api.post)

    assert [path for path, _ in api.calls] == ["/nodes", "/workers"]


def test_a_created_response_without_an_id_is_an_error() -> None:
    def post(path: str, payload: Mapping[str, object]) -> tuple[int, str]:
        return 201, "{}"

    with pytest.raises(ValueError, match="POST /nodes returned no id"):
        seed_cluster(post)


def test_a_body_that_is_not_json_is_an_error() -> None:
    def post(path: str, payload: Mapping[str, object]) -> tuple[int, str]:
        return 201, "not json"

    with pytest.raises(ValueError):
        seed_cluster(post)
