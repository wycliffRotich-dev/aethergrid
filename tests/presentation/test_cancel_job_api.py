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


def test_cancel_already_cancelled_job_returns_409() -> None:
    """
    Cancelling a job twice must not silently succeed the
    second time. The first call settles the job as
    CANCELLED; the second is a conflict with that already-
    settled outcome, not a repeat success.
    """
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

    first_cancel = client.post(
        f"/jobs/{job_id}/cancel",
    )
    assert first_cancel.status_code == 200
    assert first_cancel.json()["status"] == "CANCELLED"

    second_cancel = client.post(
        f"/jobs/{job_id}/cancel",
    )

    assert second_cancel.status_code == 409


def test_cancel_already_completed_job_returns_409() -> None:
    """
    Exercises the real end-to-end path, not a fabricated
    one: every job created through the public API today has
    command=None (ADR 0012), so ClusterTickService's
    background loop completes it within the same tick, the
    same premise test_complete_job_after_background_loop_
    already_completed_it_returns_409 in
    test_report_job_outcome_api.py already relies on. A
    cancel request arriving after that settled outcome must
    be rejected as a conflict, not silently accepted.
    """
    import time

    with TestClient(app) as with_lifespan_client:
        node_response = with_lifespan_client.post(
            "/nodes",
            json={
                "cpu_cores": 8,
                "memory_mib": 16384,
                "vram_mib": 8192,
            },
        )
        assert node_response.status_code == 201
        node_id = node_response.json()["id"]

        heartbeat_response = with_lifespan_client.post(
            f"/nodes/{node_id}/heartbeat",
        )
        assert heartbeat_response.status_code == 200

        worker_response = with_lifespan_client.post(
            "/workers",
            json={"node_id": node_id},
        )
        assert worker_response.status_code == 201

        job_response = with_lifespan_client.post(
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
        job_completed = False

        while time.monotonic() < deadline:
            job_get_response = with_lifespan_client.get(
                f"/jobs/{job_id}",
            )
            assert job_get_response.status_code == 200

            if job_get_response.json()["status"] == "COMPLETED":
                job_completed = True
                break

            time.sleep(0.05)

        assert job_completed, (
            "Job never reached COMPLETED within 3 seconds; "
            "the background loop's own execution path may "
            "have changed and this test's premise needs "
            "revisiting."
        )

        response = with_lifespan_client.post(
            f"/jobs/{job_id}/cancel",
        )

        assert response.status_code == 409
