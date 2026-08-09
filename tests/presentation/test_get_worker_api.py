import time

import pytest
from fastapi.testclient import TestClient

from app.presentation.api import app


def test_get_existing_worker_returns_200_with_no_running_job() -> None:
    """
    A freshly registered, idle worker has no running job.
    running_job must be null, not omitted or an empty object.
    """
    with TestClient(app) as client:
        node_response = client.post(
            "/nodes",
            json={
                "cpu_cores": 8,
                "memory_mib": 16384,
                "vram_mib": 8192,
            },
        )
        assert node_response.status_code == 201
        node_id = node_response.json()["id"]

        worker_response = client.post(
            "/workers",
            json={"node_id": node_id},
        )
        assert worker_response.status_code == 201
        worker_id = worker_response.json()["id"]

        response = client.get(f"/workers/{worker_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == worker_id
        assert body["node_id"] == node_id
        assert body["running_job"] is None




@pytest.mark.skip(
    reason=(
        "ClusterTickService still drives WorkerExecutionLoop "
        "every tick for any worker holding a running_job, and "
        "WorkerExecutionLoop's own guard (if not job.is_running(): "
        "worker.start()) immediately starts and completes the job "
        "in-process regardless of this change. There is no stable "
        "assigned-but-not-yet-started window until ClusterTickService "
        "stops auto-executing locally and instead leaves jobs for an "
        "agent to pick up (ADR 0019, staged step 4, deliberately "
        "deferred until the agent endpoints exist and are proven). "
        "Un-skip this once that cutover lands."
    ),
)
def test_get_worker_returns_running_job_once_assigned() -> None:
    """
    Once a job is assigned to this worker, running_job must
    reflect it, including command (even when None) and
    execution_timeout_seconds -- the exact fields ADR 0020
    scopes to this endpoint only.
    """
    with TestClient(app) as client:
        node_response = client.post(
            "/nodes",
            json={
                "cpu_cores": 8,
                "memory_mib": 16384,
                "vram_mib": 8192,
            },
        )
        node_id = node_response.json()["id"]

        heartbeat_response = client.post(
            f"/nodes/{node_id}/heartbeat",
        )
        assert heartbeat_response.status_code == 200

        worker_response = client.post(
            "/workers",
            json={"node_id": node_id},
        )
        worker_id = worker_response.json()["id"]

        job_response = client.post(
            "/jobs",
            json={
                "cpu_cores": 2,
                "memory_mib": 2048,
                "vram_mib": 0,
            },
        )
        assert job_response.status_code == 201
        job_id = job_response.json()["id"]

        deadline = time.monotonic() + 3.0
        body = None

        while time.monotonic() < deadline:
            response = client.get(f"/workers/{worker_id}")
            assert response.status_code == 200
            body = response.json()

            if body["running_job"] is not None:
                break

            time.sleep(0.05)
        else:
            raise AssertionError(
                "Worker never showed a running_job within 3 seconds."
            )

        assert body["running_job"]["id"] == job_id
        assert body["running_job"]["command"] is None
        assert body["running_job"]["execution_timeout_seconds"] > 0


def test_get_nonexistent_worker_returns_404() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/workers/00000000-0000-0000-0000-000000000000",
        )
        assert response.status_code == 404


def test_get_worker_with_malformed_id_returns_422() -> None:
    with TestClient(app) as client:
        response = client.get("/workers/not-a-valid-uuid")
        assert response.status_code == 422
