import httpx
import pytest

from app.main import create_app
from tests.concurrency_helpers import isolated_engine_pool as isolated_engine_pool


@pytest.mark.usefixtures("isolated_engine_pool")
async def test_api_root() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


async def test_health_returns_status(monkeypatch) -> None:
    async def fake_check_database() -> bool:
        return True

    monkeypatch.setattr("app.main.check_database", fake_check_database)
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "connected",
        "redis": "not_checked",
    }
