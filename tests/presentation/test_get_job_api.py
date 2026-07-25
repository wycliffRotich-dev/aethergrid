import time

from fastapi.testclient import TestClient

from app.presentation.api import app


def test_get_existing_job_returns_200() -> None:
    """
    Retrieving an existing job should return HTTP 200.

    The scheduler runs asynchronously as part of the
    application's lifespan. This test exercises the API
    exactly as a real deployment would by creating a
    TestClient lifespan, registering a healthy node,
    creating a job, waiting for the scheduler tick,
    and then verifying that the job has been scheduled.
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

        heartbeat_response = client.post(
            f"/nodes/{node_id}/heartbeat",
        )

        assert heartbeat_response.status_code == 200

        create_response = client.post(
            "/jobs",
            json={
                "cpu_cores": 4,
                "memory_mib": 4096,
                "vram_mib": 2048,
            },
        )

        assert create_response.status_code == 201

        job_id = create_response.json()["id"]

        deadline = time.monotonic() + 3.0

        while time.monotonic() < deadline:
            response = client.get(
                f"/jobs/{job_id}",
            )

            assert response.status_code == 200

            body = response.json()

            if body["status"] == "SCHEDULED":
                break

            time.sleep(0.1)
        else:
            raise AssertionError(
                "Job was not scheduled within 3 seconds."
            )

        assert body["id"] == job_id
        assert body["status"] == "SCHEDULED"
