from fastapi.testclient import TestClient

from app.presentation.api import app

client = TestClient(app)


def test_list_jobs_returns_200() -> None:
    """
    Listing jobs should return HTTP 200.
    """
    response = client.get("/jobs")

    assert response.status_code == 200

    body = response.json()

    assert "jobs" in body
    assert isinstance(body["jobs"], list)


def test_list_jobs_includes_newly_created_job() -> None:
    """
    A job just created should appear in the list response,
    exposing status and exit_code (still None before it
    runs), without ever exposing `command` -- even when a
    command was actually set (ADR 0028), not just when it
    was left as the None default. The earlier version of
    this test only proved a job with no command couldn't
    leak a command it never had; this proves the boundary
    holds when there's actually something to leak.
    """
    create_response = client.post(
        "/jobs",
        json={
            "cpu_cores": 1,
            "memory_mib": 512,
            "vram_mib": 0,
            "command": ["python", "train.py"],
        },
    )

    assert create_response.status_code == 201

    created_id = create_response.json()["id"]

    list_response = client.get("/jobs")

    assert list_response.status_code == 200

    jobs = list_response.json()["jobs"]

    matching = [job for job in jobs if job["id"] == created_id]

    assert len(matching) == 1
    assert matching[0]["exit_code"] is None
    assert "command" not in matching[0]
