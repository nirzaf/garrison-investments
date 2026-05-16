from uuid import uuid4

import httpx
import pytest

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.utils.security import hash_password

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def skip_if_database_unavailable() -> None:
    if not await check_database():
        pytest.skip("database is not available")


async def create_user(role: str, password: str = "Start123!") -> tuple[User, str]:
    user = User(
        email=f"analytics-{role}-{uuid4().hex}@example.com",
        full_name=f"{role} Analytics User",
        role=role,
        employee_code=f"ANL-{uuid4().hex[:8]}",
        phone="+97455551000",
        designation=role.replace("_", " ").title(),
        password_hash=hash_password(password),
        must_change_password=False,
    )
    async with AsyncSessionLocal() as session:
        await UserRepository(session).add(user)
        await session.commit()
        await session.refresh(user)
    return user, password


def create_test_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app())
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def login_for_token(client: httpx.AsyncClient, user: User, password: str) -> str:
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": password},
    )
    challenge = login_response.json()
    verify_response = await client.post(
        "/api/v1/auth/verify-otp",
        json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"]},
    )
    return str(verify_response.json()["access_token"])


async def test_management_analytics_and_exports_are_restricted() -> None:
    await skip_if_database_unavailable()
    manager, manager_password = await create_user("general_manager")
    engineer, engineer_password = await create_user("civil_engineer")

    async with create_test_client() as client:
        manager_token = await login_for_token(client, manager, manager_password)
        engineer_token = await login_for_token(client, engineer, engineer_password)

        summary = await client.get(
            "/api/v1/analytics/summary",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert summary.status_code == 200
        assert "projects" in summary.json()

        export = await client.get(
            "/api/v1/export/project-progress",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert export.status_code == 200
        assert export.content.startswith(b"PK")

        blocked = await client.get(
            "/api/v1/analytics/summary",
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert blocked.status_code == 403
