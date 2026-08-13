import time

from fastapi.testclient import TestClient

from app.presentation.api import app


def test_start_job_transitions_job_to_running() -> None:
    """
    Once a worker holds a job as its running_job, calling
    start must transition that job from SCHEDULED to RUNNING,
    and only that -- this is the one thing that makes RUNNING
    true, per AssignWorkerService no longer doing it at
    assignment time.
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
            json={"node_id": node_id, "managed_by": "AGENT"},
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
        job_id = job_response.json()["id"]

        deadline = time.monotonic() + 10.0
        worker_body = None

        while time.monotonic() < deadline:
            response = client.get(f"/workers/{worker_id}")
            assert response.status_code == 200
            worker_body = response.json()

            if worker_body["running_job"] is not None:
                break

            time.sleep(0.05)
        else:
            raise AssertionError(
                "Worker never showed a running_job within 10 seconds. "
                f"Last worker state: {worker_body}"
            )

        assert worker_body["running_job"]["id"] == job_id

        start_response = client.post(
            f"/workers/{worker_id}/jobs/{job_id}/start",
        )
        assert start_response.status_code == 200

        job_after_start = client.get(f"/jobs/{job_id}")
        assert job_after_start.status_code == 200


def test_start_job_with_wrong_job_id_returns_409() -> None:
    """
    A worker cannot start a job it does not currently hold.
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

        worker_response = client.post(
            "/workers",
            json={"node_id": node_id},
        )
        worker_id = worker_response.json()["id"]

        fake_job_id = "00000000-0000-0000-0000-000000000000"

        response = client.post(
            f"/workers/{worker_id}/jobs/{fake_job_id}/start",
        )
        assert response.status_code == 409


def test_start_job_with_nonexistent_worker_returns_404() -> None:
    with TestClient(app) as client:
        fake_worker_id = "00000000-0000-0000-0000-000000000000"
        fake_job_id = "00000000-0000-0000-0000-000000000000"

        response = client.post(
            f"/workers/{fake_worker_id}/jobs/{fake_job_id}/start",
        )
        assert response.status_code == 404


def test_start_job_with_malformed_worker_id_returns_422() -> None:
    with TestClient(app) as client:
        fake_job_id = "00000000-0000-0000-0000-000000000000"

        response = client.post(
            f"/workers/not-a-valid-id/jobs/{fake_job_id}/start",
        )
        assert response.status_code == 422


def test_start_job_with_malformed_job_id_returns_422() -> None:
    with TestClient(app) as client:
        fake_worker_id = "00000000-0000-0000-0000-000000000000"

        response = client.post(
            f"/workers/{fake_worker_id}/jobs/not-a-valid-id/start",
        )
        assert response.status_code == 422
