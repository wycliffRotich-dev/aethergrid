from fastapi.testclient import TestClient

from app.presentation.api import app

client = TestClient(app)


def test_list_events_returns_200() -> None:
    response = client.get("/events")

    assert response.status_code == 200


def test_list_events_returns_expected_shape() -> None:
    response = client.get("/events")

    body = response.json()

    assert "events" in body
    assert isinstance(body["events"], list)
