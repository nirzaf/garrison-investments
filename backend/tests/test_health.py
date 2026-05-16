from fastapi.testclient import TestClient

from app.main import create_app


def test_api_root() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_health_returns_status(monkeypatch) -> None:
    async def fake_check_database() -> bool:
        return True

    monkeypatch.setattr("app.main.check_database", fake_check_database)
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "connected",
        "redis": "not_checked",
    }
