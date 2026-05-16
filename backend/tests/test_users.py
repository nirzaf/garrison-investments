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


async def create_user(role: str, password: str = "Start123!") -> tuple[str, str]:
    email = f"{role}-{uuid4().hex}@example.com"
    async with AsyncSessionLocal() as session:
        await UserRepository(session).add(
            User(
                email=email,
                full_name=f"{role} User",
                role=role,
                employee_code=f"TEST-{uuid4().hex[:8]}",
                phone="+97455550000",
                designation=role.replace("_", " ").title(),
                password_hash=hash_password(password),
                must_change_password=False,
            )
        )
        await session.commit()
    return email, password


def create_test_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app())
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def login_for_token(client: httpx.AsyncClient, email: str, password: str) -> str:
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    challenge = login_response.json()
    verify_response = await client.post(
        "/api/v1/auth/verify-otp",
        json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"]},
    )
    return str(verify_response.json()["access_token"])


async def test_admin_can_create_filter_and_deactivate_users() -> None:
    await skip_if_database_unavailable()
    admin_email, admin_password = await create_user("admin")

    async with create_test_client() as client:
        token = await login_for_token(client, admin_email, admin_password)
        created_response = await client.post(
            "/api/v1/users",
            json={
                "email": f"managed-{uuid4().hex}@example.com",
                "full_name": "Managed Engineer",
                "role": "civil_engineer",
                "employee_code": f"ENG-{uuid4().hex[:8]}",
                "phone": "+97455550111",
                "designation": "Civil Engineer",
                "temporary_password": "Managed123!",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert created_response.status_code == 201
        created_user = created_response.json()
        assert created_user["role"] == "civil_engineer"

        list_response = await client.get(
            "/api/v1/users",
            params={"active": "true", "role": "civil_engineer"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert list_response.status_code == 200
        assert any(item["id"] == created_user["id"] for item in list_response.json()["items"])

        deactivate_response = await client.delete(
            f"/api/v1/users/{created_user['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert deactivate_response.status_code == 200
        assert deactivate_response.json()["is_active"] is False


async def test_operation_manager_can_read_users_but_cannot_manage_users() -> None:
    await skip_if_database_unavailable()
    op_email, op_password = await create_user("operation_manager")

    async with create_test_client() as client:
        token = await login_for_token(client, op_email, op_password)
        list_response = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert list_response.status_code == 200

        create_response = await client.post(
            "/api/v1/users",
            json={
                "email": f"blocked-{uuid4().hex}@example.com",
                "full_name": "Blocked User",
                "role": "accounts",
                "employee_code": f"ACC-{uuid4().hex[:8]}",
                "phone": "+97455550222",
                "designation": "Accounts",
                "temporary_password": "Blocked123!",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert create_response.status_code == 403
