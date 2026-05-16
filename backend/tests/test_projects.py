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
                employee_code=f"PRJ-{uuid4().hex[:8]}",
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


def project_payload() -> dict:
    return {
        "name": f"Tower Works {uuid4().hex[:6]}",
        "scope_of_work": "Civil works and fit-out scope.",
        "target_end_date": "2026-12-31",
        "location": "Doha",
        "client_name": "Garrison Client",
        "contract_number": f"CN-{uuid4().hex[:6]}",
        "milestones": [
            {
                "name": "Mobilization",
                "discipline": "civil",
                "planned_start_date": "2026-06-01",
                "planned_end_date": "2026-06-15",
                "sort_order": 1,
            }
        ],
        "boq_items": [
            {
                "item_code": "BOQ-001",
                "description": "Site preparation",
                "discipline": "civil",
                "phase": "Mobilization",
                "milestone_name": "Mobilization",
                "unit": "lot",
                "planned_quantity": "1",
                "unit_rate": "1500",
            }
        ],
    }


async def test_operation_manager_creates_project_with_boq_and_timeline() -> None:
    await skip_if_database_unavailable()
    op_email, op_password = await create_user("operation_manager")

    async with create_test_client() as client:
        token = await login_for_token(client, op_email, op_password)
        create_response = await client.post(
            "/api/v1/projects",
            json=project_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )

        assert create_response.status_code == 201
        project = create_response.json()
        assert project["code"]

        detail_response = await client.get(
            f"/api/v1/projects/{project['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert len(detail["boq_items"]) == 1
        assert len(detail["milestones"]) == 1
        assert detail["is_read_only"] is False

        timeline_response = await client.get(
            f"/api/v1/projects/{project['id']}/timeline",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert timeline_response.status_code == 200
        assert timeline_response.json()["milestones"][0]["name"] == "Mobilization"


async def test_assigned_engineer_can_read_assigned_project_only() -> None:
    await skip_if_database_unavailable()
    op_email, op_password = await create_user("operation_manager")
    engineer_email, engineer_password = await create_user("civil_engineer")

    async with create_test_client() as client:
        op_token = await login_for_token(client, op_email, op_password)
        engineer_token = await login_for_token(client, engineer_email, engineer_password)
        project = (
            await client.post(
                "/api/v1/projects",
                json=project_payload(),
                headers={"Authorization": f"Bearer {op_token}"},
            )
        ).json()
        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assign_response = await client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": me.json()["id"], "role_in_project": "site_engineer"},
            headers={"Authorization": f"Bearer {op_token}"},
        )

        assert assign_response.status_code == 201

        detail_response = await client.get(
            f"/api/v1/projects/{project['id']}",
            headers={"Authorization": f"Bearer {engineer_token}"},
        )

        assert detail_response.status_code == 200


async def test_completed_project_is_read_only() -> None:
    await skip_if_database_unavailable()
    op_email, op_password = await create_user("operation_manager")

    async with create_test_client() as client:
        token = await login_for_token(client, op_email, op_password)
        project = (
            await client.post(
                "/api/v1/projects",
                json=project_payload(),
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()

        complete_response = await client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"status": "completed", "actual_end_date": "2026-12-30"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert complete_response.status_code == 200

        update_response = await client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"name": "Changed Name"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert update_response.status_code == 409
