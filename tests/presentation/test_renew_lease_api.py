import pytest
from fastapi.testclient import TestClient

from app.presentation.api import app


@pytest.mark.skip(
    reason=(
        "Same root cause as test_start_job_transitions_job_to_running "
        "in test_start_job_api.py: jobs created through the public API "
        "have no command (ADR 0012), so JobExecutionService completes "
        "them synchronously and near-instantly once assigned. By the "
        "time any polling loop observes a worker holding a running_job, "
        "the lease backing it has almost always already been acquired "
        "and released within the same tick, leaving no stable window "
        "to renew against. Manually verified via curl against a live "
        "instance: job went QUEUED -> RUNNING -> COMPLETED in under "
        "1.1 seconds with no command set. Blocked on the same thing as "
        "the /start test: ADR 0019 stage 4, real out-of-process "
        "execution with a genuine gap between holding a lease and "
        "finishing the job."
    ),
)
def test_renew_lease_succeeds_while_worker_holds_a_job() -> None:
    """
    Renewing the lease a worker actually holds must return 200
    and extend its expiry, without changing the worker's status
    or the job it's holding.
    """
    raise NotImplementedError(
        "See skip reason -- no stable window exists yet to "
        "exercise this against a real held lease."
    )


def test_renew_lease_with_no_active_lease_returns_409() -> None:
    """
    A worker that exists but holds no lease, whether it never
    acquired one or already released it, must return 409, not
    404 -- the worker itself is real, only the lease is missing.
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

        response = client.post(
            f"/workers/{worker_id}/lease/renew",
        )
        assert response.status_code == 409


def test_renew_lease_with_nonexistent_worker_returns_404() -> None:
    with TestClient(app) as client:
        fake_worker_id = "00000000-0000-0000-0000-000000000000"

        response = client.post(
            f"/workers/{fake_worker_id}/lease/renew",
        )
        assert response.status_code == 404


def test_renew_lease_with_malformed_worker_id_returns_422() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/workers/not-a-valid-id/lease/renew",
        )
        assert response.status_code == 422
