from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_register_worker_returns_201() -> None:
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

    response = client.post(
        "/workers",
        json={
            "node_id": node_id,
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert isinstance(body["id"], str)
    assert body["status"] == "IDLE"