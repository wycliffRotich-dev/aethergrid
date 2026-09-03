import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.presentation.api import app


def test_a_long_running_job_does_not_block_other_requests() -> None:
    """
    Before ADR 0032, ClusterTickService.execute() ran directly
    on the event loop; a job with a real, long-running command
    would block every other request for its full execution
    duration. Since ADR 0032 moved that call to a worker thread
    via asyncio.to_thread, the server must stay responsive to
    an unrelated request while a job's command is still running.

    WorkerExecutionLoop only persists the job's own row once,
    at completion, so job.status never observably reads RUNNING
    from outside; the worker's own status flips to BUSY at
    assignment and stays there for the job's entire execution,
    which is the reliable, externally observable signal that
    execution is genuinely in progress.

    This submits a job that sleeps for 2 real seconds, waits
    for its worker to go BUSY, then fires a concurrent,
    unrelated request and asserts it completes almost
    immediately rather than waiting for the job to finish. 2
    seconds is short enough to keep this test fast but long
    enough to give a still-blocking event loop no way to hide
    behind scheduling noise.
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
                "cpu_cores": 1,
                "memory_mib": 512,
                "vram_mib": 0,
                "command": ["sleep", "2"],
            },
        )
        assert job_response.status_code == 201
        job_id = job_response.json()["id"]

        deadline = time.monotonic() + 5.0

        while time.monotonic() < deadline:
            worker_status_response = client.get(f"/workers/{worker_id}")
            assert worker_status_response.status_code == 200

            if worker_status_response.json()["status"] == "BUSY":
                break

            time.sleep(0.05)
        else:
            raise AssertionError(
                "Worker never went BUSY within 5 seconds."
            )

        with ThreadPoolExecutor(max_workers=1) as executor:
            start = time.monotonic()
            future = executor.submit(client.get, "/nodes")
            response = future.result(timeout=1.0)
            elapsed = time.monotonic() - start

        assert response.status_code == 200
        assert elapsed < 1.0, (
            "A concurrent request took "
            f"{elapsed:.2f}s while the worker was BUSY executing "
            "a job; the event loop appears to be blocked by job "
            "execution."
        )

        deadline = time.monotonic() + 5.0
        completed_body = None

        while time.monotonic() < deadline:
            status_response = client.get(f"/jobs/{job_id}")
            completed_body = status_response.json()

            if completed_body["status"] == "COMPLETED":
                break

            time.sleep(0.1)
        else:
            raise AssertionError(
                "Job never reached COMPLETED within 5 seconds."
            )

        assert completed_body["exit_code"] == 0
        assert completed_body["started_at"] is not None
        assert completed_body["completed_at"] is not None
