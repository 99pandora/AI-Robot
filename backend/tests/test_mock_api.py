from fastapi.testclient import TestClient

from backend.mock_api.main import app

client = TestClient(app)


def test_mock_api_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["service"] == "xiaosu-mock-api"


def test_attendance_accepts_short_user_id() -> None:
    response = client.get("/api/attendance", params={"user_id": "001"})

    assert response.status_code == 200
    assert response.json()
    assert {item["userId"] for item in response.json()} == {"U001"}


def test_orders_filters_by_date_range() -> None:
    response = client.get(
        "/api/orders", params={"start_date": "2026-08-14", "end_date": "2026-08-14"}
    )

    assert response.status_code == 200
    assert len(response.json()) == 2
