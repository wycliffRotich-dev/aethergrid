import time

from fastapi.testclient import TestClient

from app.presentation.api import app


def test_complete_job_with_malformed_worker_id_returns_422() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/workers/not-a-valid-uuid"
            "/jobs/00000000-0000-0000-0000-000000000000/complete",
            json={},
        )

        assert response.status_code == 422


def test_complete_job_with_malformed_job_id_returns_422() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/workers/00000000-0000-0000-0000-000000000000"
            "/jobs/not-a-valid-uuid/complete",
            json={},
        )

        assert response.status_code == 422


def test_complete_job_for_nonexistent_worker_returns_404() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/workers/00000000-0000-0000-0000-000000000000"
            "/jobs/00000000-0000-0000-0000-000000000000/complete",
            json={},
        )

        assert response.status_code == 404


def test_complete_job_when_worker_holds_no_job_returns_409() -> None:
    """
    A freshly registered, idle worker has no running_job.
    Reporting an outcome for any job against it must be
    rejected as a mismatch, not silently accepted.
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

        response = client.post(
            f"/workers/{worker_id}/jobs/"
            "00000000-0000-0000-0000-000000000000/complete",
            json={},
        )

        assert response.status_code == 409


def test_fail_job_with_malformed_worker_id_returns_422() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/workers/not-a-valid-uuid"
            "/jobs/00000000-0000-0000-0000-000000000000/fail",
            json={},
        )

        assert response.status_code == 422


def test_fail_job_with_malformed_job_id_returns_422() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/workers/00000000-0000-0000-0000-000000000000"
            "/jobs/not-a-valid-uuid/fail",
            json={},
        )

        assert response.status_code == 422


def test_fail_job_for_nonexistent_worker_returns_404() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/workers/00000000-0000-0000-0000-000000000000"
            "/jobs/00000000-0000-0000-0000-000000000000/fail",
            json={},
        )

        assert response.status_code == 404


def test_fail_job_when_worker_holds_no_job_returns_409() -> None:
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

        response = client.post(
            f"/workers/{worker_id}/jobs/"
            "00000000-0000-0000-0000-000000000000/fail",
            json={},
        )

        assert response.status_code == 409


def test_complete_job_after_background_loop_already_completed_it_returns_409() -> (
    None
):
    """
    Exercises the real, current end-to-end path rather than a
    fabricated one. Every job created through the public API
    today has command=None (ADR 0012), which JobExecutionService
    treats as an instant no-op success, so ClusterTickService's
    background loop starts and completes an assigned job within
    the same tick, with no stable RUNNING window to catch from
    outside the process. This is the same reason
    test_get_worker_returns_running_job_once_assigned in
    test_get_worker_api.py is skipped rather than polled: the
    window it would poll for does not exist yet.

    So the true "happy path" for this endpoint, as the system
    behaves today, is that by the time any external caller
    reports an outcome, the loop has usually already reported one
    itself and released the lease -- and this endpoint's job is
    to recognize that and refuse the stale report with 409, per
    ReportJobOutcomeService's own "drop it on the floor"
    docstring. Once ADR 0019's real external agent path lands and
    auto-execution is no longer the default, a genuine 200-path
    test replaces this one, the same way the skipped GET test is
    meant to be un-skipped at that point.
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

        worker_response = client.post(
            "/workers",
            json={"node_id": node_id},
        )
        assert worker_response.status_code == 201
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
        job_completed = False

        while time.monotonic() < deadline:
            job_get_response = client.get(f"/jobs/{job_id}")
            assert job_get_response.status_code == 200

            if job_get_response.json()["status"] == "COMPLETED":
                job_completed = True
                break

            time.sleep(0.05)

        assert job_completed, (
            "Job never reached COMPLETED within 3 seconds; "
            "the background loop's own execution path may have "
            "changed and this test's premise needs revisiting."
        )

        response = client.post(
            f"/workers/{worker_id}/jobs/{job_id}/complete",
            json={},
        )

        assert response.status_code == 409
