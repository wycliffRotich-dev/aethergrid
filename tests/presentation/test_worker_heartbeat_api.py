from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_heartbeat_recovers_offline_worker_with_no_running_job() -> None:
    """
    ADR 0041, end to end through the real HTTP surface: register a
    worker, force it OFFLINE the same way reconciliation would
    (directly through the repository, since no HTTP path exists to
    do this and the real 60s HEARTBEAT_TIMEOUT is too slow for a
    test), then confirm a real POST /workers/{id}/heartbeat call
    brings it back to IDLE.

    This reproduces the exact scenario observed live: a worker whose
    heartbeat lapsed while genuinely idle, with no way back to IDLE
    before this fix except manual re-registration.
    """
    from app.domain.value_objects.worker_id import WorkerId
    from app.presentation.dependencies import _worker_repository

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
        json={
            "node_id": node_id,
        },
    )
    assert worker_response.status_code == 201
    worker_id = worker_response.json()["id"]
    assert worker_response.json()["status"] == "IDLE"

    worker = _worker_repository.get_by_id(
        WorkerId(worker_id),
    )
    assert worker is not None
    assert worker.running_job is None

    worker.offline()
    _worker_repository.save(worker)

    offline_check = client.get(f"/workers/{worker_id}")
    assert offline_check.status_code == 200
    assert offline_check.json()["status"] == "OFFLINE"

    heartbeat_response = client.post(
        f"/workers/{worker_id}/heartbeat",
    )
    assert heartbeat_response.status_code == 200

    recovered = client.get(f"/workers/{worker_id}")
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "IDLE"
