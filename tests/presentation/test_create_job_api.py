from fastapi.testclient import TestClient

from app.presentation.api import app

client = TestClient(app)


def test_create_job_returns_201() -> None:
    """
    Creating a job through the API should return
    HTTP 201.

    When no compute nodes are available the job
    should immediately enter the QUEUED state.
    """

    response = client.post(
        "/jobs",
        json={
            "cpu_cores": 4,
            "memory_mib": 4096,
            "vram_mib": 2048,
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert "id" in body
    assert body["status"] == "QUEUED"


def test_create_job_accepts_command() -> None:
    """
    A caller may set a command when creating a job (ADR
    0028). The response still never echoes it back --
    CreateJobResponse only ever returns id and status.
    """
    response = client.post(
        "/jobs",
        json={
            "cpu_cores": 1,
            "memory_mib": 512,
            "vram_mib": 0,
            "command": ["python", "train.py"],
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert "id" in body
    assert body["status"] == "QUEUED"
    assert "command" not in body


def test_create_job_rejects_empty_command_list() -> None:
    response = client.post(
        "/jobs",
        json={
            "cpu_cores": 1,
            "memory_mib": 512,
            "vram_mib": 0,
            "command": [],
        },
    )

    assert response.status_code == 422
