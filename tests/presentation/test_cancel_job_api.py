from fastapi.testclient import TestClient

from app.presentation.api import app

client = TestClient(app)


def test_cancel_queued_job_returns_200() -> None:
    create_response = client.post(
        "/jobs",
        json={
            "cpu_cores": 1,
            "memory_mib": 512,
            "vram_mib": 0,
        },
    )
    assert create_response.status_code == 201
    job_id = create_response.json()["id"]

    cancel_response = client.post(
        f"/jobs/{job_id}/cancel",
    )

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "CANCELLED"


def test_cancel_nonexistent_job_returns_404() -> None:
    response = client.post(
        "/jobs/11111111-1111-1111-1111-111111111111/cancel",
    )

    assert response.status_code == 404
